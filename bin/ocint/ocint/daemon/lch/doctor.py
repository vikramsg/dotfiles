import os
import shutil
import socket
import sqlite3
import stat
import subprocess
import tomllib
from pathlib import Path

import click
from pydantic import BaseModel, ConfigDict

from ocint.daemon.config import DaemonConfig, DaemonSettings
from ocint.daemon.db import current_daemon_head_revision
from ocint.daemon.lch.provision import (
    RestrictedOpenCodeConfig,
    StaticOpenCodePolicy,
    discovery_environment,
    load_policy,
    policy_resource_path,
)
from ocint.daemon.lch.systemd import CommandRunner, SystemdLifecycle, service_text, timer_text


class Diagnostic(BaseModel):
    model_config = ConfigDict(frozen=True)
    name: str
    required: bool
    ok: bool
    value: str
    detail: str = ""


class DoctorReport(BaseModel):
    model_config = ConfigDict(frozen=True)
    diagnostics: tuple[Diagnostic, ...]

    @property
    def healthy(self) -> bool:
        return all(item.ok for item in self.diagnostics if item.required)

    def json_text(self) -> str:
        return DoctorEnvelope(healthy=self.healthy, diagnostics=self.diagnostics).model_dump_json(indent=2) + "\n"

    def human_text(self) -> str:
        lines = ["ocint daemon doctor"]
        for item in self.diagnostics:
            status = "ok" if item.ok else ("FAIL" if item.required else "warn")
            suffix = f" — {item.detail}" if item.detail else ""
            lines.append(f"[{status}] {item.name}: {item.value}{suffix}")
        return "\n".join(lines) + "\n"


class DoctorEnvelope(BaseModel):
    model_config = ConfigDict(frozen=True)
    healthy: bool
    diagnostics: tuple[Diagnostic, ...]


class CommandObservation(BaseModel):
    model_config = ConfigDict(frozen=True)
    value: str = ""
    error: str = ""


def diagnose(home: Path, runner: CommandRunner, lifecycle: SystemdLifecycle) -> DoctorReport:
    diagnostics: list[Diagnostic] = []
    settings = DaemonSettings()
    config_path = settings.config_path(home)
    diagnostics.append(_private_file_diagnostic("config.path", config_path))
    config: DaemonConfig | None = None
    try:
        if not _owned_regular(config_path, 0o600):
            raise ValueError("daemon config must be a user-owned regular non-symlink mode-0600 file")
        with config_path.open("rb") as stream:
            config = DaemonConfig.model_validate(tomllib.load(stream))
        effective = config.model_dump_json(exclude_none=True)
        diagnostics.append(Diagnostic(name="config.effective", required=True, ok=True, value=effective))
    except (OSError, ValueError, tomllib.TOMLDecodeError) as error:
        diagnostics.append(
            Diagnostic(name="config.effective", required=True, ok=False, value="unavailable", detail=str(error))
        )

    environment = lifecycle.paths.environment_file
    diagnostics.append(_private_file_diagnostic("env.path", environment))
    names = ("OCINT_DAEMON_API_TOKEN", "OCINT_DAEMON_GITHUB_TOKEN")
    present = _environment_presence(environment, names)
    for name in names:
        diagnostics.append(
            Diagnostic(
                name=f"env.{name}",
                required=True,
                ok=name in present,
                value="present" if name in present else "missing",
                detail="" if name in present else f"add {name} to the mode-0600 environment file",
            )
        )

    policy: StaticOpenCodePolicy | None = None
    try:
        policy, payload = load_policy()
        diagnostics.append(
            Diagnostic(
                name="opencode.packaged_policy",
                required=True,
                ok=True,
                value=policy.model_dump_json(by_alias=True),
                detail=f"resource={policy_resource_path()}; bytes={len(payload)}",
            )
        )
    except (OSError, ValueError, click.ClickException) as error:
        diagnostics.append(
            Diagnostic(name="opencode.packaged_policy", required=True, ok=False, value="unavailable", detail=str(error))
        )

    if config is None:
        for name in (
            "opencode.effective_config",
            "opencode.executable_version",
            "opencode.model_provider",
            "opencode.config_paths",
            "opencode.isolated_directories",
            "opencode.auth",
            "database",
            "mirror_root",
            "worktree_root",
            "database.migration",
            "ports.private_opencode",
            "ports.api",
            "git.remote_author_ssh",
        ):
            diagnostics.append(
                Diagnostic(name=name, required=True, ok=False, value="unavailable", detail="config invalid")
            )
    else:
        diagnostics.extend(_opencode_diagnostics(config, runner, home, policy))
        diagnostics.extend(_storage_diagnostics(config))
        diagnostics.extend(_git_diagnostics(config))
        diagnostics.append(_port_diagnostic("ports.private_opencode", config.opencode.server_url.port or 80))
        diagnostics.append(_port_diagnostic("ports.api", config.api.port))

    repository = config.repositories[0].github_repository if config is not None else ""
    diagnostics.extend(_github_diagnostics(runner, home, repository))
    diagnostics.extend(_systemd_diagnostics(lifecycle, runner))
    return DoctorReport(diagnostics=tuple(diagnostics))


def _opencode_diagnostics(
    config: DaemonConfig,
    runner: CommandRunner,
    home: Path,
    policy: StaticOpenCodePolicy | None,
) -> list[Diagnostic]:
    result: list[Diagnostic] = []
    try:
        if not _owned_regular(config.opencode.config_file, 0o600):
            raise ValueError("effective OpenCode config must be user-owned, regular, non-symlink, and mode 0600")
        effective = RestrictedOpenCodeConfig.model_validate_json(config.opencode.config_file.read_text())
        policy_matches = policy is not None and _effective_policy_matches(effective, policy, config.worktree_root)
        result.append(
            Diagnostic(
                name="opencode.effective_config",
                required=True,
                ok=policy_matches and _owned_regular(config.opencode.config_file, 0o600),
                value=effective.model_dump_json(by_alias=True, exclude_none=True),
                detail=(
                    f"path={config.opencode.config_file}; mode={_mode(config.opencode.config_file)}; "
                    f"policy_preserved={policy_matches}"
                ),
            )
        )
        result.append(
            Diagnostic(
                name="opencode.model_provider",
                required=True,
                ok=True,
                value=f"{effective.model} / {','.join(effective.provider)}",
            )
        )
    except (OSError, ValueError) as error:
        result.append(
            Diagnostic(
                name="opencode.effective_config", required=True, ok=False, value="unavailable", detail=str(error)
            )
        )
        result.append(Diagnostic(name="opencode.model_provider", required=True, ok=False, value="unavailable"))
    version_observation = _observe_isolated(
        runner,
        (str(config.opencode.executable), "--version"),
        discovery_environment(home, False),
    )
    version = version_observation.value
    result.append(
        Diagnostic(
            name="opencode.executable_version",
            required=True,
            ok=version == "1.17.20" and config.opencode.expected_version == "1.17.20",
            value=f"{config.opencode.executable} ({version or 'unavailable'})",
            detail=version_observation.error or "required and configured version must both be 1.17.20",
        )
    )
    source = Path(os.environ.get("XDG_DATA_HOME", home / ".local" / "share")) / "opencode" / "auth.json"
    source_config = Path(os.environ.get("XDG_CONFIG_HOME", home / ".config")) / "opencode" / "opencode.json"
    result.append(
        Diagnostic(
            name="opencode.config_paths",
            required=True,
            ok=source_config.is_file() and _owned_regular(config.opencode.config_file, 0o600),
            value=(
                f"source={source_config}; effective={config.opencode.config_file}; "
                f"isolated_config={config.opencode.xdg_config_home}"
            ),
        )
    )
    isolated_config_ok = _private_directory(config.opencode.xdg_config_home)
    isolated_data_ok = _private_directory(config.opencode.xdg_data_home)
    result.append(
        Diagnostic(
            name="opencode.isolated_directories",
            required=True,
            ok=isolated_config_ok and isolated_data_ok,
            value=(
                f"config={config.opencode.xdg_config_home} (mode={_mode(config.opencode.xdg_config_home)}); "
                f"data={config.opencode.xdg_data_home} (mode={_mode(config.opencode.xdg_data_home)})"
            ),
            detail=(
                f"config_owner_ok={_owned(config.opencode.xdg_config_home)}; "
                f"data_owner_ok={_owned(config.opencode.xdg_data_home)}"
            ),
        )
    )
    link = config.opencode.xdg_data_home / "opencode" / "auth.json"
    safe = (
        _owned_regular(source, 0o600)
        and link.is_symlink()
        and link.lstat().st_uid == os.getuid()
        and link.resolve() == source.resolve()
    )
    result.append(
        Diagnostic(
            name="opencode.auth",
            required=True,
            ok=safe,
            value=f"source={source}; link={link}; isolated_data={config.opencode.xdg_data_home}",
            detail=(
                f"source_mode={_mode(source)}; source_owner_ok={_owned(source)}; "
                f"link_owner_ok={_owned(link)}; link_is_symlink={link.is_symlink()}"
            ),
        )
    )
    return result


def _storage_diagnostics(config: DaemonConfig) -> list[Diagnostic]:
    result = [
        _private_file_diagnostic("database", config.database_path),
        _directory_diagnostic("mirror_root", config.mirror_root),
        _directory_diagnostic("worktree_root", config.worktree_root),
    ]
    revision = "missing"
    if _owned_regular(config.database_path, 0o600):
        try:
            uri = f"file:{config.database_path}?mode=ro"
            with sqlite3.connect(uri, uri=True) as connection:
                row = connection.execute("SELECT version_num FROM alembic_version").fetchone()
            revision = str(row[0]) if row is not None else "missing"
        except sqlite3.Error as error:
            revision = f"unreadable: {error}"
    expected = current_daemon_head_revision()
    result.append(
        Diagnostic(
            name="database.migration", required=True, ok=revision == expected, value=revision, detail=f"head={expected}"
        )
    )
    return result


def _git_diagnostics(config: DaemonConfig) -> list[Diagnostic]:
    repository = config.repositories[0]
    identity_ok = _owned_regular(config.git.identity_file, 0o600)
    known_ok = config.git.known_hosts_file.is_file() and os.access(config.git.known_hosts_file, os.R_OK)
    executable_ok = _system_executable(config.git.ssh_executable)
    return [
        Diagnostic(
            name="git.remote_author_ssh",
            required=True,
            ok=identity_ok and known_ok and executable_ok,
            value=(
                f"remote={repository.remote_url}; author={repository.author_name} <{repository.author_email}>; "
                f"ssh={config.git.ssh_executable}; identity={config.git.identity_file}; "
                f"known_hosts={config.git.known_hosts_file}"
            ),
        )
    ]


def _github_diagnostics(runner: CommandRunner, home: Path, repository: str) -> list[Diagnostic]:
    commands = (
        ("github.login", ("gh", "api", "--hostname", "github.com", "user")),
        (
            "github.repository_default_branch",
            ("gh", "repo", "view", repository, "--json", "nameWithOwner,defaultBranchRef"),
        ),
        ("github.token", ("gh", "auth", "token", "--hostname", "github.com")),
    )
    result: list[Diagnostic] = []
    environment = discovery_environment(home, True)
    for name, command in commands:
        if name == "github.repository_default_branch" and not repository:
            result.append(
                Diagnostic(
                    name=name,
                    required=True,
                    ok=False,
                    value="unavailable",
                    detail="daemon config is invalid; repository is unavailable",
                )
            )
            continue
        observation = _observe_isolated(runner, command, environment)
        value = observation.value
        shown = "present" if name == "github.token" and value else ("missing" if name == "github.token" else value)
        detail = "" if name == "github.token" else observation.error
        if name == "github.token" and observation.error:
            detail = "gh auth token failed; authenticate gh for github.com"
        result.append(Diagnostic(name=name, required=True, ok=bool(value), value=shown or "unavailable", detail=detail))
    return result


def _systemd_diagnostics(lifecycle: SystemdLifecycle, runner: CommandRunner) -> list[Diagnostic]:
    paths = lifecycle.paths
    service_content = _read(paths.service)
    timer_content = _read(paths.timer)
    active_observation = _observe(
        runner, ("systemctl", "--user", "show", "ocint-daemon.timer", "--property=ActiveState", "--value")
    )
    schedule_observation = _observe(
        runner,
        ("systemctl", "--user", "show", "ocint-daemon.timer", "--property=NextElapseUSecRealtime", "--value"),
    )
    linger_observation = _observe(
        runner, ("loginctl", "show-user", os.environ.get("USER", ""), "--property=Linger", "--value")
    )
    active = active_observation.value
    schedule = schedule_observation.value
    linger = linger_observation.value
    executable = shutil.which("ocint")
    expected_service = (
        service_text(
            Path(executable).resolve(),
            paths.environment_reference,
            paths.reference(paths.config_home),
            paths.reference(paths.data_home),
            paths.reference(paths.daemon_config),
        )
        if executable is not None
        else ""
    )
    service_safe = _owned_regular(paths.service, 0o644)
    timer_safe = _owned_regular(paths.timer, 0o644)
    return [
        Diagnostic(
            name="systemd.service",
            required=True,
            ok=service_safe and bool(expected_service) and service_content == expected_service,
            value=f"{paths.service}\n{service_content}",
            detail=(
                f"mode={_mode(paths.service)}; owner_ok={_owned(paths.service)}; "
                f"payload_exact={bool(expected_service) and service_content == expected_service}; "
                f"expected_executable={executable or 'ocint not found on PATH'}"
            ),
        ),
        Diagnostic(
            name="systemd.timer",
            required=True,
            ok=timer_safe and timer_content == timer_text(),
            value=f"{paths.timer}\n{timer_content}",
            detail=(
                f"mode={_mode(paths.timer)}; owner_ok={_owned(paths.timer)}; "
                f"payload_exact={timer_content == timer_text()}"
            ),
        ),
        Diagnostic(
            name="systemd.state",
            required=True,
            ok=active == "active",
            value=active or "unavailable",
            detail=active_observation.error,
        ),
        Diagnostic(
            name="systemd.schedule",
            required=False,
            ok=bool(schedule),
            value=schedule or "unavailable",
            detail=schedule_observation.error,
        ),
        Diagnostic(
            name="systemd.linger",
            required=True,
            ok=linger == "yes",
            value=linger or "unavailable",
            detail=linger_observation.error,
        ),
    ]


def _environment_presence(path: Path, names: tuple[str, ...]) -> frozenset[str]:
    if not _owned_regular(path, 0o600):
        return frozenset()
    present = {line.partition("=")[0] for line in _read(path).splitlines() if "=" in line and line.partition("=")[2]}
    return frozenset(name for name in names if name in present)


def _private_file_diagnostic(name: str, path: Path) -> Diagnostic:
    safe = _owned_regular(path, 0o600)
    return Diagnostic(
        name=name,
        required=True,
        ok=safe,
        value=f"{path} (mode={_mode(path)})",
        detail=f"owner_ok={_owned(path)}; regular_non_symlink={path.is_file() and not path.is_symlink()}",
    )


def _directory_diagnostic(name: str, path: Path) -> Diagnostic:
    safe = _private_directory(path)
    return Diagnostic(
        name=name,
        required=True,
        ok=safe,
        value=f"{path} (mode={_mode(path)})",
        detail=f"owner_ok={_owned(path)}; directory_non_symlink={path.is_dir() and not path.is_symlink()}",
    )


def _mode(path: Path) -> str:
    return f"{stat.S_IMODE(path.stat().st_mode):04o}" if path.exists() else "missing"


def _port_diagnostic(name: str, port: int) -> Diagnostic:
    available = True
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            listener.bind(("127.0.0.1", port))
    except OSError:
        available = False
    return Diagnostic(name=name, required=True, ok=available, value=f"127.0.0.1:{port} available={available}")


def _observe(runner: CommandRunner, arguments: tuple[str, ...]) -> CommandObservation:
    try:
        return CommandObservation(value=runner.run(arguments).stdout.strip())
    except subprocess.TimeoutExpired:
        return CommandObservation(error=f"command timed out after 30 seconds: {' '.join(arguments)}")
    except subprocess.CalledProcessError as error:
        detail = error.stderr.strip() if isinstance(error.stderr, str) and error.stderr.strip() else str(error)
        return CommandObservation(error=f"command failed: {' '.join(arguments)}: {detail[:500]}")
    except (OSError, RuntimeError) as error:
        return CommandObservation(error=f"command could not run: {' '.join(arguments)}: {error}")


def _observe_isolated(
    runner: CommandRunner,
    arguments: tuple[str, ...],
    environment: dict[str, str],
) -> CommandObservation:
    try:
        return CommandObservation(value=runner.run_isolated(arguments, environment).stdout.strip())
    except subprocess.TimeoutExpired:
        return CommandObservation(error=f"command timed out after 30 seconds: {' '.join(arguments)}")
    except subprocess.CalledProcessError as error:
        detail = error.stderr.strip() if isinstance(error.stderr, str) and error.stderr.strip() else str(error)
        return CommandObservation(error=f"command failed: {' '.join(arguments)}: {detail[:500]}")
    except (OSError, RuntimeError) as error:
        return CommandObservation(error=f"command could not run: {' '.join(arguments)}: {error}")


def _owned(path: Path) -> bool:
    try:
        return path.lstat().st_uid == os.getuid()
    except OSError:
        return False


def _owned_regular(path: Path, expected_mode: int = -1) -> bool:
    return (
        path.is_file()
        and not path.is_symlink()
        and _owned(path)
        and (expected_mode < 0 or stat.S_IMODE(path.stat().st_mode) == expected_mode)
    )


def _private_directory(path: Path) -> bool:
    return path.is_dir() and not path.is_symlink() and _owned(path) and _mode(path) == "0700"


def _system_executable(path: Path) -> bool:
    return path == path.resolve() and path.is_file() and os.access(path, os.X_OK)


def _effective_policy_matches(
    effective: RestrictedOpenCodeConfig,
    policy: StaticOpenCodePolicy,
    worktree_root: Path,
) -> bool:
    return (
        effective.schema_url == policy.schema_url
        and effective.share == policy.share
        and effective.instructions == policy.instructions
        and effective.plugin == policy.plugin
        and effective.agent == policy.agent
        and effective.lsp == policy.lsp
        and effective.formatter == policy.formatter
        and effective.permission.model_copy(update={"external_directory": {"*": "deny"}}) == policy.permission
        and effective.permission.external_directory == {"*": "deny", f"{worktree_root.resolve()}/**": "allow"}
    )


def _read(path: Path) -> str:
    try:
        return path.read_text() if path.is_file() else "missing"
    except OSError as error:
        return f"unreadable: {error}"
