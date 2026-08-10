import asyncio
import json
import os
import shutil
import socket
import sqlite3
import stat
import subprocess
from contextlib import suppress
from datetime import UTC, datetime
from ipaddress import ip_address
from pathlib import Path

import click
from pydantic import BaseModel, ConfigDict

from ocint.daemon.config import DaemonConfig, DaemonContext
from ocint.daemon.db import current_daemon_head_revision
from ocint.daemon.lch.opencode import (
    CoordinatorRestrictedOpenCodeConfig,
    CoordinatorStaticOpenCodePolicy,
    OpenCodeSourceConfig,
    PrivateFilePurpose,
    PrivateFileRequirement,
    RestrictedOpenCodeConfig,
    StaticOpenCodePolicy,
    coordinator_policy_resource_path,
    load_coordinator_policy,
    load_policy,
    policy_resource_path,
    private_file_is_valid,
    restricted_agent_config,
    validate_private_file,
)
from ocint.daemon.lch.setup import discovery_environment
from ocint.daemon.lch.systemd import (
    CommandRunner,
    NgrokRuntime,
    SystemdLifecycle,
    coordinator_ngrok_service_text,
    coordinator_service_text,
    discover_ngrok,
    service_text,
    timer_text,
)
from ocint.daemon.logging import daemon_log_settings
from ocint.daemon.slack import check_slack_access


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


def diagnose(context: DaemonContext, runner: CommandRunner, lifecycle: SystemdLifecycle) -> DoctorReport:
    diagnostics: list[Diagnostic] = []
    config_path = context.config_path
    diagnostics.append(_private_file_diagnostic("config.path", config_path))
    config: DaemonConfig | None = None
    try:
        validate_private_file(PrivateFileRequirement(path=config_path, purpose=PrivateFilePurpose.DAEMON_CONFIG))
        config = context.config()
        effective = config.model_dump_json(exclude_none=True)
        diagnostics.append(Diagnostic(name="config.effective", required=True, ok=True, value=effective))
    except (OSError, ValueError, click.ClickException) as error:
        diagnostics.append(
            Diagnostic(name="config.effective", required=True, ok=False, value="unavailable", detail=str(error))
        )

    environment = lifecycle.paths.environment_file
    diagnostics.append(_private_file_diagnostic("env.path", environment))
    names = (
        "OCINT_DAEMON_API_TOKEN",
        "OCINT_DAEMON_GITHUB_TOKEN",
        "OCINT_DAEMON_SLACK_BOT_TOKEN",
        "OCINT_DAEMON_SLACK_SIGNING_SECRET",
        "OCINT_NGROK_URL",
    )
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

    ngrok: NgrokRuntime | None = None
    try:
        ngrok = discover_ngrok(runner, environment)
        diagnostics.extend(
            (
                Diagnostic(
                    name="ngrok.executable_version",
                    required=True,
                    ok=True,
                    value=f"{ngrok.executable} ({ngrok.version})",
                ),
                Diagnostic(name="ngrok.url", required=True, ok=True, value="valid static HTTPS URL"),
            )
        )
    except (OSError, RuntimeError, subprocess.CalledProcessError) as error:
        diagnostics.extend(
            (
                Diagnostic(
                    name="ngrok.executable_version",
                    required=True,
                    ok=False,
                    value="unavailable",
                    detail=str(error),
                ),
                Diagnostic(name="ngrok.url", required=True, ok=False, value="invalid", detail=str(error)),
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

    coordinator_policy: CoordinatorStaticOpenCodePolicy | None = None
    try:
        coordinator_policy, payload = load_coordinator_policy()
        diagnostics.append(
            Diagnostic(
                name="coordinator.opencode.packaged_policy",
                required=True,
                ok=True,
                value=coordinator_policy.model_dump_json(by_alias=True),
                detail=f"resource={coordinator_policy_resource_path()}; bytes={len(payload)}",
            )
        )
    except (OSError, ValueError, click.ClickException) as error:
        diagnostics.append(
            Diagnostic(
                name="coordinator.opencode.packaged_policy",
                required=True,
                ok=False,
                value="unavailable",
                detail=str(error),
            )
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
            "daemon.log",
            "mirror_root",
            "worktree_root",
            "database.migration",
            "ports.private_opencode",
            "ports.api",
            "git.remote_author_ssh",
            "coordinator.opencode.effective_config",
            "coordinator.opencode.executable_version",
            "coordinator.opencode.paths",
            "coordinator.workspace",
            "ports.coordinator_ingress",
            "ports.coordinator_opencode",
            "ports.distinct_loopback",
            "slack.access",
        ):
            diagnostics.append(
                Diagnostic(name=name, required=True, ok=False, value="unavailable", detail="config invalid")
            )
    else:
        diagnostics.extend(_opencode_diagnostics(config, runner, context, policy))
        diagnostics.extend(_coordinator_diagnostics(config, runner, context, coordinator_policy))
        diagnostics.extend(_storage_diagnostics(config, daemon_log_settings(context.state_home, config.logging).path))
        diagnostics.extend(_git_diagnostics(config))
        service_active = (
            _observe(
                runner,
                ("systemctl", "--user", "show", "ocint-daemon.service", "--property=ActiveState", "--value"),
            ).value
            == "active"
        )
        diagnostics.append(
            _port_diagnostic(
                "ports.private_opencode", config.opencode.server_url.port or 80, occupied_allowed=service_active
            )
        )
        diagnostics.append(_port_diagnostic("ports.api", config.api.port, occupied_allowed=service_active))
        coordinator_active = (
            _observe(
                runner,
                ("systemctl", "--user", "show", "ocint-coordinator.service", "--property=ActiveState", "--value"),
            ).value
            == "active"
        )
        diagnostics.append(
            _port_diagnostic(
                "ports.coordinator_ingress",
                config.coordinator.ingress.port,
                occupied_allowed=coordinator_active,
            )
        )
        diagnostics.append(
            _port_diagnostic(
                "ports.coordinator_opencode",
                config.coordinator.opencode.server_url.port or 80,
                occupied_allowed=coordinator_active,
            )
        )
        diagnostics.append(_distinct_loopback_ports_diagnostic(config))
        token = _environment_value(environment, "OCINT_DAEMON_SLACK_BOT_TOKEN")
        try:
            value = asyncio.run(check_slack_access(config.coordinator.slack, token)) if token else "token missing"
            diagnostics.append(Diagnostic(name="slack.access", required=True, ok=bool(token), value=value))
        except Exception as error:
            diagnostics.append(
                Diagnostic(name="slack.access", required=True, ok=False, value="unavailable", detail=str(error))
            )

    repository = config.repositories[0].github_repository if config is not None else ""
    diagnostics.extend(_github_diagnostics(runner, context, repository))
    diagnostics.extend(_systemd_diagnostics(lifecycle, runner, config, ngrok))
    return DoctorReport(diagnostics=tuple(diagnostics))


def _opencode_diagnostics(
    config: DaemonConfig,
    runner: CommandRunner,
    context: DaemonContext,
    policy: StaticOpenCodePolicy | None,
) -> list[Diagnostic]:
    result: list[Diagnostic] = []
    try:
        if not _owned_regular(config.opencode.config_file, 0o600):
            raise ValueError("effective OpenCode config must be user-owned, regular, non-symlink, and mode 0600")
        effective = RestrictedOpenCodeConfig.model_validate_json(config.opencode.config_file.read_text())
        source_path = validate_private_file(
            PrivateFileRequirement(
                path=context.config_home / "opencode" / "opencode.json",
                purpose=PrivateFilePurpose.SOURCE_OPENCODE_CONFIG,
            )
        ).path
        source = OpenCodeSourceConfig.model_validate_json(source_path.read_text())
        policy_matches = policy is not None and _effective_policy_matches(
            effective,
            policy,
            config.worktree_root,
            source.agent.build.options.service_tier,
        )
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
    except (OSError, ValueError, click.ClickException) as error:
        result.append(
            Diagnostic(
                name="opencode.effective_config", required=True, ok=False, value="unavailable", detail=str(error)
            )
        )
        result.append(Diagnostic(name="opencode.model_provider", required=True, ok=False, value="unavailable"))
    version_observation = _observe_isolated(
        runner,
        (str(config.opencode.executable), "--version"),
        discovery_environment(context, False),
    )
    version = version_observation.value
    result.append(
        Diagnostic(
            name="opencode.executable_version",
            required=True,
            ok=version == "1.18.15" and config.opencode.expected_version == "1.18.15",
            value=f"{config.opencode.executable} ({version or 'unavailable'})",
            detail=version_observation.error or "required and configured version must both be 1.18.15",
        )
    )
    source = context.data_home / "opencode" / "auth.json"
    source_config = context.config_home / "opencode" / "opencode.json"
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


def _coordinator_diagnostics(
    config: DaemonConfig,
    runner: CommandRunner,
    context: DaemonContext,
    policy: CoordinatorStaticOpenCodePolicy | None,
) -> list[Diagnostic]:
    coordinator = config.coordinator
    service = coordinator.opencode
    result: list[Diagnostic] = []
    try:
        if not _owned_regular(service.config_file, 0o600):
            raise ValueError("coordinator OpenCode config must be user-owned, regular, non-symlink, and mode 0600")
        effective = CoordinatorRestrictedOpenCodeConfig.model_validate_json(service.config_file.read_text())
        source_path = context.config_home / "opencode" / "opencode.json"
        source = OpenCodeSourceConfig.model_validate_json(source_path.read_text())
        policy_matches = (
            policy is not None
            and effective.model_dump(exclude={"model", "provider"}) == policy.model_dump()
            and effective.model == source.model
            and tuple(effective.provider) == (source.model.partition("/")[0],)
        )
        result.append(
            Diagnostic(
                name="coordinator.opencode.effective_config",
                required=True,
                ok=policy_matches,
                value=effective.model_dump_json(by_alias=True, exclude_none=True),
                detail=(
                    f"path={service.config_file}; mode={_mode(service.config_file)}; policy_preserved={policy_matches}"
                ),
            )
        )
    except (OSError, ValueError, click.ClickException) as error:
        result.append(
            Diagnostic(
                name="coordinator.opencode.effective_config",
                required=True,
                ok=False,
                value="unavailable",
                detail=str(error),
            )
        )
    version_observation = _observe_isolated(
        runner,
        (str(service.executable), "--version"),
        discovery_environment(context, False),
    )
    version = version_observation.value
    result.append(
        Diagnostic(
            name="coordinator.opencode.executable_version",
            required=True,
            ok=version == "1.18.15" and service.expected_version == "1.18.15",
            value=f"{service.executable} ({version or 'unavailable'})",
            detail=version_observation.error or "required and configured version must both be 1.18.15",
        )
    )
    source_auth = context.data_home / "opencode" / "auth.json"
    auth_link = service.xdg_data_home / "opencode" / "auth.json"
    paths_ok = (
        _private_directory(service.xdg_config_home)
        and _private_directory(service.xdg_data_home)
        and _owned_regular(service.config_file, 0o600)
        and _owned_regular(source_auth, 0o600)
        and auth_link.is_symlink()
        and auth_link.lstat().st_uid == os.getuid()
        and auth_link.resolve() == source_auth.resolve()
    )
    result.append(
        Diagnostic(
            name="coordinator.opencode.paths",
            required=True,
            ok=paths_ok,
            value=(
                f"config={service.config_file}; config_home={service.xdg_config_home}; "
                f"data_home={service.xdg_data_home}; auth_link={auth_link}"
            ),
            detail=(
                f"config_mode={_mode(service.config_file)}; config_home_mode={_mode(service.xdg_config_home)}; "
                f"data_home_mode={_mode(service.xdg_data_home)}"
            ),
        )
    )
    workspace = coordinator.workspace_root
    agents = workspace / "AGENTS.md"
    catalogue = workspace / "repositories.json"
    expected_catalogue = {
        "repositories": [
            {
                "name": repository.name,
                "description": repository.description,
                "github_repository": repository.github_repository,
                "default_branch": repository.default_branch,
            }
            for repository in config.repositories
        ]
    }
    catalogue_matches = False
    with suppress(OSError, json.JSONDecodeError):
        catalogue_matches = json.loads(catalogue.read_text()) == expected_catalogue
    workspace_files_absent = not agents.exists() and not catalogue.exists()
    workspace_files_safe = _owned_regular(agents, 0o600) and _owned_regular(catalogue, 0o600) and catalogue_matches
    workspace_ok = _private_directory(workspace) and (workspace_files_absent or workspace_files_safe)
    result.append(
        Diagnostic(
            name="coordinator.workspace",
            required=True,
            ok=workspace_ok,
            value=f"root={workspace}; agents={agents}; catalogue={catalogue}",
            detail=(
                f"root_mode={_mode(workspace)}; agents_mode={_mode(agents)}; "
                f"catalogue_mode={_mode(catalogue)}; catalogue_exact={catalogue_matches}; "
                f"runtime_owned_pending={workspace_files_absent}"
            ),
        )
    )
    return result


def _storage_diagnostics(config: DaemonConfig, log_path: Path) -> list[Diagnostic]:
    result = [
        _private_file_diagnostic("database", config.database_path),
        _directory_diagnostic("mirror_root", config.mirror_root),
        _directory_diagnostic("worktree_root", config.worktree_root),
        _log_diagnostic(log_path, config.logging.backup_count),
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
            name="database.migration",
            required=False,
            ok=revision == expected,
            value=revision,
            detail=f"head={expected}; timer/coordinator startup owns migration",
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


def _github_diagnostics(runner: CommandRunner, context: DaemonContext, repository: str) -> list[Diagnostic]:
    commands = (
        ("github.login", ("gh", "api", "--hostname", "github.com", "user")),
        (
            "github.repository_default_branch",
            ("gh", "repo", "view", repository, "--json", "nameWithOwner,defaultBranchRef"),
        ),
        ("github.token", ("gh", "auth", "token", "--hostname", "github.com")),
    )
    result: list[Diagnostic] = []
    environment = discovery_environment(context, True)
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


def _systemd_diagnostics(
    lifecycle: SystemdLifecycle,
    runner: CommandRunner,
    config: DaemonConfig | None,
    ngrok: NgrokRuntime | None,
) -> list[Diagnostic]:
    paths = lifecycle.paths
    service_content = _read(paths.service)
    timer_content = _read(paths.timer)
    coordinator_content = _read(paths.coordinator_service)
    ngrok_content = _read(paths.coordinator_ngrok_service)
    active_observation = _observe(
        runner, ("systemctl", "--user", "show", "ocint-daemon.timer", "--property=ActiveState", "--value")
    )
    schedule_observation = _observe(
        runner,
        (
            "systemctl",
            "--user",
            "list-timers",
            "--all",
            "ocint-daemon.timer",
            "--output=json",
            "--no-pager",
        ),
    )
    linger_observation = _observe(
        runner, ("loginctl", "show-user", lifecycle.paths.user, "--property=Linger", "--value")
    )
    active = active_observation.value
    schedule = _timer_schedule(schedule_observation.value)
    linger = linger_observation.value
    executable = shutil.which("ocint")
    expected_service = (
        service_text(
            Path(executable).resolve(),
            paths.environment_reference,
            paths.reference(paths.config_home),
            paths.reference(paths.data_home),
            paths.reference(paths.state_home),
            paths.reference(paths.daemon_config),
        )
        if executable is not None
        else ""
    )
    service_safe = _owned_regular(paths.service, 0o644)
    timer_safe = _owned_regular(paths.timer, 0o644)
    expected_coordinator = (
        coordinator_service_text(
            Path(executable).resolve(),
            paths.environment_reference,
            paths.reference(paths.config_home),
            paths.reference(paths.data_home),
            paths.reference(paths.state_home),
            paths.reference(paths.daemon_config),
        )
        if executable is not None
        else ""
    )
    expected_ngrok = (
        coordinator_ngrok_service_text(
            ngrok,
            paths.reference(paths.home),
            paths.reference(paths.config_home),
            "C.UTF-8",
            config.coordinator.ingress.port,
        )
        if config is not None and ngrok is not None
        else ""
    )
    coordinator_safe = _owned_regular(paths.coordinator_service, 0o644)
    ngrok_safe = _owned_regular(paths.coordinator_ngrok_service, 0o644)
    coordinator_state = _observe(
        runner,
        ("systemctl", "--user", "show", "ocint-coordinator.service", "--property=ActiveState", "--value"),
    )
    ngrok_state = _observe(
        runner,
        (
            "systemctl",
            "--user",
            "show",
            "ocint-coordinator-ngrok.service",
            "--property=ActiveState",
            "--value",
        ),
    )
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
            ok=timer_safe and config is not None and timer_content == timer_text(config.lifecycle),
            value=f"{paths.timer}\n{timer_content}",
            detail=(
                f"mode={_mode(paths.timer)}; owner_ok={_owned(paths.timer)}; "
                f"payload_exact={config is not None and timer_content == timer_text(config.lifecycle)}"
            ),
        ),
        Diagnostic(
            name="systemd.coordinator_service",
            required=True,
            ok=coordinator_safe and bool(expected_coordinator) and coordinator_content == expected_coordinator,
            value=f"{paths.coordinator_service}\n{coordinator_content}",
            detail=(
                f"mode={_mode(paths.coordinator_service)}; owner_ok={_owned(paths.coordinator_service)}; "
                f"payload_exact={bool(expected_coordinator) and coordinator_content == expected_coordinator}"
            ),
        ),
        Diagnostic(
            name="systemd.coordinator_ngrok_service",
            required=True,
            ok=ngrok_safe and bool(expected_ngrok) and ngrok_content == expected_ngrok,
            value=(
                f"{paths.coordinator_ngrok_service}\n"
                f"{ngrok_content.replace(ngrok.url, '<redacted-static-url>') if ngrok is not None else ngrok_content}"
            ),
            detail=(
                f"mode={_mode(paths.coordinator_ngrok_service)}; owner_ok={_owned(paths.coordinator_ngrok_service)}; "
                f"payload_exact={bool(expected_ngrok) and ngrok_content == expected_ngrok}"
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
            name="systemd.coordinator_state",
            required=False,
            ok=coordinator_state.value == "active",
            value=coordinator_state.value or "inactive",
            detail=coordinator_state.error or "unit may remain inactive before production rollout",
        ),
        Diagnostic(
            name="systemd.coordinator_ngrok_state",
            required=False,
            ok=ngrok_state.value == "active",
            value=ngrok_state.value or "inactive",
            detail=ngrok_state.error or "unit may remain inactive before production rollout",
        ),
        Diagnostic(
            name="systemd.linger",
            required=True,
            ok=linger == "yes",
            value=linger or "unavailable",
            detail=linger_observation.error,
        ),
    ]


def _timer_schedule(payload: str) -> str:
    try:
        timers = json.loads(payload)
    except json.JSONDecodeError:
        return ""
    if not isinstance(timers, list) or not timers or not isinstance(timers[0], dict):
        return ""
    timer = timers[0]
    last = timer.get("last")
    next_trigger = timer.get("next")
    if not isinstance(last, int):
        return ""
    rendered_last = datetime.fromtimestamp(last / 1_000_000, UTC).isoformat().replace("+00:00", "Z")
    rendered_next = (
        datetime.fromtimestamp(next_trigger / 1_000_000, UTC).isoformat().replace("+00:00", "Z")
        if isinstance(next_trigger, int)
        else "pending service completion"
    )
    return f"last={rendered_last}; next={rendered_next}"


def _environment_presence(path: Path, names: tuple[str, ...]) -> frozenset[str]:
    if not _owned_regular(path, 0o600):
        return frozenset()
    present = {line.partition("=")[0] for line in _read(path).splitlines() if "=" in line and line.partition("=")[2]}
    return frozenset(name for name in names if name in present)


def _environment_value(path: Path, name: str) -> str:
    if not _owned_regular(path, 0o600):
        return ""
    return next(
        (line.partition("=")[2] for line in _read(path).splitlines() if line.partition("=")[0] == name),
        "",
    )


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
        required=path.exists(),
        ok=safe,
        value=f"{path} (mode={_mode(path)})",
        detail=f"owner_ok={_owned(path)}; directory_non_symlink={path.is_dir() and not path.is_symlink()}",
    )


def _log_diagnostic(path: Path, backup_count: int) -> Diagnostic:
    safe = _owned_regular(path, 0o600)
    rotated = len(tuple(path.parent.glob(f"{path.name}.[1-{backup_count}]"))) if path.parent.is_dir() else 0
    return Diagnostic(
        name="daemon.log",
        required=path.exists(),
        ok=safe,
        value=f"{path} (mode={_mode(path)})",
        detail=(
            f"owner_ok={_owned(path)}; size={path.stat().st_size if safe else 0}; "
            f"rotated={rotated}; backup_count={backup_count}"
        ),
    )


def _mode(path: Path) -> str:
    return f"{stat.S_IMODE(path.stat().st_mode):04o}" if path.exists() else "missing"


def _port_diagnostic(name: str, port: int, occupied_allowed: bool = False) -> Diagnostic:
    available = True
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            listener.bind(("127.0.0.1", port))
    except OSError:
        available = False
    return Diagnostic(
        name=name,
        required=True,
        ok=available or occupied_allowed,
        value=f"127.0.0.1:{port} available={available}",
        detail="occupied by active daemon service" if not available and occupied_allowed else "",
    )


def _distinct_loopback_ports_diagnostic(config: DaemonConfig) -> Diagnostic:
    hosts = (
        config.api.host,
        config.coordinator.ingress.host,
        config.opencode.server_url.host or "",
        config.coordinator.opencode.server_url.host or "",
    )
    ports = (
        config.api.port,
        config.coordinator.ingress.port,
        config.opencode.server_url.port,
        config.coordinator.opencode.server_url.port,
    )
    loopback = all(ip_address(host).is_loopback for host in hosts)
    distinct = None not in ports and len(set(ports)) == 4
    return Diagnostic(
        name="ports.distinct_loopback",
        required=True,
        ok=loopback and distinct,
        value=", ".join(f"{host}:{port}" for host, port in zip(hosts, ports, strict=True)),
        detail=f"loopback={loopback}; distinct={distinct}",
    )


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


def _owned_regular(path: Path, expected_mode: int) -> bool:
    return private_file_is_valid(
        PrivateFileRequirement(
            path=path,
            purpose=PrivateFilePurpose.MANAGED_CONFIG,
            mode=expected_mode,
        )
    )


def _private_directory(path: Path) -> bool:
    return path.is_dir() and not path.is_symlink() and _owned(path) and _mode(path) == "0700"


def _system_executable(path: Path) -> bool:
    return path == path.resolve() and path.is_file() and os.access(path, os.X_OK)


def _effective_policy_matches(
    effective: RestrictedOpenCodeConfig,
    policy: StaticOpenCodePolicy,
    worktree_root: Path,
    service_tier: str | None,
) -> bool:
    return (
        effective.schema_url == policy.schema_url
        and effective.share == policy.share
        and effective.instructions == policy.instructions
        and effective.plugin == policy.plugin
        and effective.agent == restricted_agent_config(service_tier)
        and effective.lsp == policy.lsp
        and effective.formatter == policy.formatter
        and effective.permission.model_copy(update={"external_directory": {"*": "deny"}}) == policy.permission
        and effective.permission.external_directory
        == {"*": "deny", "/tmp/**": "allow", f"{worktree_root.resolve()}/**": "allow"}
    )


def _read(path: Path) -> str:
    try:
        return path.read_text() if path.is_file() else "missing"
    except OSError as error:
        return f"unreadable: {error}"
