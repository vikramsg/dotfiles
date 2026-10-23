import json
import os
import platform
import re
import shutil
import stat
import subprocess
from collections.abc import Iterator, Mapping, Sequence
from datetime import UTC, datetime
from ipaddress import ip_address
from pathlib import Path
from typing import Protocol
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict

from ocint.daemon.config import LifecycleConfig
from ocint.daemon.logging import DaemonLogSettings, follow_log, read_log_tail


class CommandResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    stdout: str = ""
    stderr: str = ""


class NgrokRuntime(BaseModel):
    model_config = ConfigDict(frozen=True)

    executable: Path
    version: str
    url: str


class LifecycleStatus(BaseModel):
    model_config = ConfigDict(frozen=True)

    installed: bool
    timer_state: str = "inactive"
    timer_substate: str = "dead"
    last_trigger: str = "unavailable"
    next_trigger: str = "unavailable"
    service_state: str = "inactive"
    service_substate: str = "dead"
    last_result: str = "unknown"
    last_exit_status: str = "unknown"
    last_started: str = "unavailable"
    last_completed: str = "unavailable"
    coordinator_state: str = "inactive"
    coordinator_substate: str = "dead"
    coordinator_unit_state: str = "disabled"
    ngrok_state: str = "inactive"
    ngrok_substate: str = "dead"
    ngrok_unit_state: str = "disabled"
    log_path: Path
    home: Path


class CoordinatorUnitEnablement(BaseModel):
    model_config = ConfigDict(frozen=True)

    coordinator: str
    ngrok: str


class CommandRunner(Protocol):
    def run(self, arguments: Sequence[str]) -> CommandResult: ...
    def run_isolated(self, arguments: Sequence[str], environment: Mapping[str, str]) -> CommandResult: ...
    def run_interactive(self, arguments: Sequence[str], environment: Mapping[str, str]) -> None: ...


class SubprocessRunner:
    def __init__(self, timeout_seconds: int = 30) -> None:
        self.timeout_seconds = timeout_seconds

    def run(self, arguments: Sequence[str]) -> CommandResult:
        environment = scrubbed_subprocess_environment(os.environ)
        environment.update(self._noninteractive_environment())
        if "--follow" in arguments:
            subprocess.run(arguments, check=True, env=environment, stdin=subprocess.DEVNULL)
            return CommandResult()
        return self._run(arguments, environment)

    def run_isolated(self, arguments: Sequence[str], environment: Mapping[str, str]) -> CommandResult:
        isolated = scrubbed_subprocess_environment(environment, allow_operational_credentials=True)
        isolated.update(self._noninteractive_environment())
        return self._run(arguments, isolated)

    def run_interactive(self, arguments: Sequence[str], environment: Mapping[str, str]) -> None:
        subprocess.run(
            arguments,
            check=True,
            env=scrubbed_subprocess_environment(environment, allow_operational_credentials=True),
        )

    @staticmethod
    def _noninteractive_environment() -> dict[str, str]:
        return {
            "PAGER": "cat",
            "GIT_PAGER": "cat",
            "GH_PAGER": "cat",
            "GIT_TERMINAL_PROMPT": "0",
            "GH_PROMPT_DISABLED": "1",
        }

    def _run(self, arguments: Sequence[str], environment: Mapping[str, str]) -> CommandResult:
        result = subprocess.run(
            arguments,
            check=True,
            capture_output=True,
            text=True,
            env=environment,
            stdin=subprocess.DEVNULL,
            timeout=self.timeout_seconds,
        )
        return CommandResult(stdout=result.stdout, stderr=result.stderr)


def scrubbed_subprocess_environment(
    environment: Mapping[str, str], *, allow_operational_credentials: bool = False
) -> dict[str, str]:
    scrubbed = dict(environment)
    sensitive_names = (
        "GH_TOKEN",
        "GITHUB_TOKEN",
        "OCINT_DAEMON_API_TOKEN",
        "OCINT_DAEMON_GITHUB_TOKEN",
        "OCINT_DAEMON_SLACK_BOT_TOKEN",
        "OCINT_DAEMON_SLACK_SIGNING_SECRET",
        "OCINT_E2E_SLACK_ACTOR_USER_TOKEN",
        "OCINT_NGROK_URL",
    )
    names = ("OCINT_E2E_SLACK_ACTOR_USER_TOKEN",) if allow_operational_credentials else sensitive_names
    for name in names:
        scrubbed.pop(name, None)
    return scrubbed


class SystemdPaths(BaseModel):
    model_config = ConfigDict(frozen=True)
    directory: Path
    environment_file: Path
    config_home: Path
    data_home: Path
    state_home: Path
    daemon_config: Path
    home: Path
    user: str = ""

    @property
    def service(self) -> Path:
        return self.directory / "ocint-daemon.service"

    @property
    def timer(self) -> Path:
        return self.directory / "ocint-daemon.timer"

    @property
    def coordinator_service(self) -> Path:
        return self.directory / "ocint-coordinator.service"

    @property
    def coordinator_ngrok_service(self) -> Path:
        return self.directory / "ocint-coordinator-ngrok.service"

    @property
    def environment_reference(self) -> str:
        return self.reference(self.environment_file)

    def reference(self, path: Path) -> str:
        resolved = path.resolve()
        home = self.home.resolve()
        try:
            relative = resolved.relative_to(home)
        except ValueError:
            return str(resolved)
        return f"%h/{relative.as_posix()}"


def timer_text(config: LifecycleConfig) -> str:
    return f"""[Unit]
Description=Schedule ocint daemon

[Timer]
OnStartupSec={systemd_duration(config.startup_delay_seconds)}
OnUnitInactiveSec={systemd_duration(config.inactive_interval_seconds)}
Unit=ocint-daemon.service

[Install]
WantedBy=timers.target
"""


def service_text(
    executable: Path,
    environment_file: str,
    config_home: str,
    data_home: str,
    state_home: str,
    daemon_config: str,
) -> str:
    return f"""[Unit]
Description=Run one ocint daemon cycle

[Service]
Type=oneshot
UMask=0077
EnvironmentFile={environment_file}
Environment=XDG_CONFIG_HOME={config_home}
Environment=XDG_DATA_HOME={data_home}
Environment=XDG_STATE_HOME={state_home}
Environment=OCINT_DAEMON_CONFIG={daemon_config}
ExecStart={executable} daemon run
TimeoutStartSec=infinity
"""


def coordinator_service_text(
    executable: Path,
    environment_file: str,
    config_home: str,
    data_home: str,
    state_home: str,
    daemon_config: str,
) -> str:
    return f"""[Unit]
Description=Run the ocint Slack coordinator
Wants=network-online.target
After=network-online.target

[Service]
Type=simple
UMask=0077
KillMode=mixed
EnvironmentFile={environment_file}
Environment=XDG_CONFIG_HOME={config_home}
Environment=XDG_DATA_HOME={data_home}
Environment=XDG_STATE_HOME={state_home}
Environment=OCINT_DAEMON_CONFIG={daemon_config}
ExecStart={executable} daemon coordinator run
Restart=on-failure
RestartSec=5s

[Install]
WantedBy=default.target
"""


def coordinator_ngrok_command(
    runtime: NgrokRuntime,
    home: str,
    config_home: str,
    lang: str,
    ingress_port: int,
) -> tuple[str, ...]:
    return (
        "/usr/bin/env",
        "-i",
        f"HOME={home}",
        f"XDG_CONFIG_HOME={config_home}",
        f"LANG={lang}",
        str(runtime.executable),
        "http",
        f"--url={runtime.url}",
        "--inspect=false",
        f"http://127.0.0.1:{ingress_port}",
    )


def coordinator_ngrok_service_text(
    runtime: NgrokRuntime,
    home: str,
    config_home: str,
    lang: str,
    ingress_port: int,
) -> str:
    command = " ".join(coordinator_ngrok_command(runtime, home, config_home, lang, ingress_port))
    return f"""[Unit]
Description=Expose the ocint Slack coordinator through ngrok
Wants=network-online.target
Requires=ocint-coordinator.service
After=network-online.target ocint-coordinator.service

[Service]
Type=simple
UMask=0077
ExecStart={command}
Restart=on-failure
RestartSec=5s

[Install]
WantedBy=default.target
"""


class SystemdLifecycle:
    def __init__(self, paths: SystemdPaths, runner: CommandRunner) -> None:
        self.paths = paths
        self.runner = runner

    def install(
        self,
        executable: Path,
        config: LifecycleConfig,
        coordinator_ingress_port: int,
        ngrok: NgrokRuntime,
    ) -> CoordinatorUnitEnablement:
        self.validate_host()
        executable = self.validate_executable(executable)
        self._validate_environment()
        ngrok = validate_ngrok_runtime(self.runner, ngrok)
        self.validate_lingering()
        self.validate_install_paths()
        self.paths.directory.mkdir(parents=True, exist_ok=True)
        self.paths.timer.write_text(timer_text(config))
        self.paths.timer.chmod(0o644)
        self.paths.service.write_text(
            service_text(
                executable,
                self.paths.environment_reference,
                self.paths.reference(self.paths.config_home),
                self.paths.reference(self.paths.data_home),
                self.paths.reference(self.paths.state_home),
                self.paths.reference(self.paths.daemon_config),
            )
        )
        self.paths.service.chmod(0o644)
        self.paths.coordinator_service.write_text(
            coordinator_service_text(
                executable,
                self.paths.environment_reference,
                self.paths.reference(self.paths.config_home),
                self.paths.reference(self.paths.data_home),
                self.paths.reference(self.paths.state_home),
                self.paths.reference(self.paths.daemon_config),
            )
        )
        self.paths.coordinator_service.chmod(0o644)
        self.paths.coordinator_ngrok_service.write_text(
            coordinator_ngrok_service_text(
                ngrok,
                self.paths.reference(self.paths.home),
                self.paths.reference(self.paths.config_home),
                "C.UTF-8",
                coordinator_ingress_port,
            )
        )
        self.paths.coordinator_ngrok_service.chmod(0o644)
        self.runner.run(("systemctl", "--user", "daemon-reload"))
        self.runner.run(("systemctl", "--user", "enable", "--now", "ocint-daemon.timer"))
        return self.coordinator_unit_enablement()

    def coordinator_unit_enablement(self) -> CoordinatorUnitEnablement:
        coordinator = self._unit_properties("ocint-coordinator.service", ("UnitFileState",))
        ngrok = self._unit_properties("ocint-coordinator-ngrok.service", ("UnitFileState",))
        return CoordinatorUnitEnablement(
            coordinator=coordinator.get("UnitFileState", "unknown"),
            ngrok=ngrok.get("UnitFileState", "unknown"),
        )

    def uninstall(self) -> None:
        self.runner.run(("systemctl", "--user", "disable", "--now", "ocint-coordinator-ngrok.service"))
        self.runner.run(("systemctl", "--user", "disable", "--now", "ocint-coordinator.service"))
        self.runner.run(("systemctl", "--user", "disable", "--now", "ocint-daemon.timer"))
        self.runner.run(("systemctl", "--user", "stop", "ocint-daemon.service"))
        self.paths.timer.unlink(missing_ok=True)
        self.paths.service.unlink(missing_ok=True)
        self.paths.coordinator_service.unlink(missing_ok=True)
        self.paths.coordinator_ngrok_service.unlink(missing_ok=True)
        self.runner.run(("systemctl", "--user", "daemon-reload"))

    def status(self, log_path: Path) -> LifecycleStatus:
        installed = all(
            path.is_file()
            for path in (
                self.paths.timer,
                self.paths.service,
                self.paths.coordinator_service,
                self.paths.coordinator_ngrok_service,
            )
        )
        if not installed:
            return LifecycleStatus(installed=False, log_path=log_path, home=self.paths.home)
        timer = self._unit_properties("ocint-daemon.timer", ("ActiveState", "SubState", "LastTriggerUSec"))
        service = self._unit_properties(
            "ocint-daemon.service",
            (
                "ActiveState",
                "SubState",
                "Result",
                "ExecMainStatus",
                "ExecMainStartTimestamp",
                "ExecMainExitTimestamp",
            ),
        )
        coordinator = self._unit_properties("ocint-coordinator.service", ("ActiveState", "SubState", "UnitFileState"))
        ngrok = self._unit_properties("ocint-coordinator-ngrok.service", ("ActiveState", "SubState", "UnitFileState"))
        schedule = json.loads(
            self.runner.run(
                (
                    "systemctl",
                    "--user",
                    "list-timers",
                    "--all",
                    "ocint-daemon.timer",
                    "--output=json",
                    "--no-pager",
                )
            ).stdout
            or "[]"
        )
        next_trigger = "unavailable"
        last_trigger = timer.get("LastTriggerUSec", "unavailable") or "unavailable"
        if schedule:
            next_value = schedule[0].get("next")
            last_value = schedule[0].get("last")
            if isinstance(next_value, int):
                next_trigger = self._timestamp(next_value)
            elif service.get("ActiveState") == "active":
                next_trigger = "pending service completion"
            if isinstance(last_value, int):
                last_trigger = self._timestamp(last_value)
        return LifecycleStatus(
            installed=True,
            timer_state=timer.get("ActiveState", "unknown"),
            timer_substate=timer.get("SubState", "unknown"),
            last_trigger=last_trigger,
            next_trigger=next_trigger,
            service_state=service.get("ActiveState", "unknown"),
            service_substate=service.get("SubState", "unknown"),
            last_result=service.get("Result", "unknown") or "unknown",
            last_exit_status=service.get("ExecMainStatus", "unknown") or "unknown",
            last_started=self._systemd_timestamp(service.get("ExecMainStartTimestamp", "")),
            last_completed=self._systemd_timestamp(service.get("ExecMainExitTimestamp", "")),
            coordinator_state=coordinator.get("ActiveState", "unknown"),
            coordinator_substate=coordinator.get("SubState", "unknown"),
            coordinator_unit_state=coordinator.get("UnitFileState", "unknown"),
            ngrok_state=ngrok.get("ActiveState", "unknown"),
            ngrok_substate=ngrok.get("SubState", "unknown"),
            ngrok_unit_state=ngrok.get("UnitFileState", "unknown"),
            log_path=log_path,
            home=self.paths.home,
        )

    def logs(self, settings: DaemonLogSettings, lines: int) -> str:
        return read_log_tail(settings, lines)

    def follow_logs(self, settings: DaemonLogSettings, lines: int) -> Iterator[str]:
        return follow_log(settings, lines)

    def api_token(self) -> str:
        self._validate_environment()
        for line in self.paths.environment_file.read_text().splitlines():
            if line.startswith("OCINT_DAEMON_API_TOKEN="):
                token = line.partition("=")[2]
                if token:
                    return token
        raise RuntimeError(f"OCINT_DAEMON_API_TOKEN is missing from {self.paths.environment_file}")

    def _unit_properties(self, unit: str, names: tuple[str, ...]) -> dict[str, str]:
        result = self.runner.run(
            ("systemctl", "--user", "show", unit, *(f"--property={name}" for name in names))
        ).stdout
        return dict(line.partition("=")[::2] for line in result.splitlines() if "=" in line)

    @staticmethod
    def _timestamp(microseconds: int) -> str:
        return datetime.fromtimestamp(microseconds / 1_000_000, UTC).strftime("%Y-%m-%d %H:%M:%S UTC")

    @staticmethod
    def _systemd_timestamp(value: str) -> str:
        if not value:
            return "unavailable"
        try:
            parsed = datetime.strptime(value, "%a %Y-%m-%d %H:%M:%S %Z").replace(tzinfo=UTC)
        except ValueError:
            return value
        return parsed.strftime("%Y-%m-%d %H:%M:%S UTC")

    def _validate_environment(self) -> None:
        path = self.paths.environment_file
        if (
            path.is_symlink()
            or not path.is_file()
            or path.stat().st_uid != os.getuid()
            or stat.S_IMODE(path.stat().st_mode) != 0o600
        ):
            raise RuntimeError(f"environment file must exist, be user-owned, and mode 0600: {path}")

    def validate_executable(self, executable: Path) -> Path:
        resolved = executable.expanduser().resolve()
        if not resolved.is_file() or not os.access(resolved, os.X_OK):
            raise RuntimeError(f"ocint executable must be an executable regular file: {resolved}")
        daemon_help = self.runner.run((str(resolved), "daemon", "--help")).stdout
        daemon_commands = {
            line.strip().split(maxsplit=1)[0] for line in daemon_help.splitlines() if line.startswith("  ")
        }
        if not {"run", "doctor", "lch"}.issubset(daemon_commands):
            raise RuntimeError(f"ocint executable does not expose daemon run, doctor, and lch: {resolved}")
        lch_help = self.runner.run((str(resolved), "daemon", "lch", "--help")).stdout
        lch_commands = {line.strip().split(maxsplit=1)[0] for line in lch_help.splitlines() if line.startswith("  ")}
        required = {"setup", "apply", "uninstall", "lifecycle", "list", "status", "attach", "logs", "slack-token"}
        if not required.issubset(lch_commands):
            raise RuntimeError(f"ocint executable does not expose the required daemon lch commands: {resolved}")
        return resolved

    def validate_host(self) -> None:
        if platform.system() != "Linux":
            raise RuntimeError("ocint daemon lch requires Linux")

    def validate_lingering(self) -> None:
        lingering = self.runner.run(
            ("loginctl", "show-user", self.paths.user, "--property=Linger", "--value")
        ).stdout.strip()
        if lingering != "yes":
            raise RuntimeError('user lingering is disabled; run loginctl enable-linger "$USER"')

    def validate_install_paths(self) -> None:
        if self.paths.directory.is_symlink() or (self.paths.directory.exists() and not self.paths.directory.is_dir()):
            raise RuntimeError(f"systemd user directory must be a regular directory: {self.paths.directory}")
        for path in (
            self.paths.timer,
            self.paths.service,
            self.paths.coordinator_service,
            self.paths.coordinator_ngrok_service,
        ):
            if path.is_symlink() or (path.exists() and (not path.is_file() or path.stat().st_uid != os.getuid())):
                raise RuntimeError(f"generated unit path must be a regular file: {path}")


def installed_ocint() -> Path:
    executable = shutil.which("ocint")
    if executable is None:
        raise RuntimeError("ocint executable is not installed on PATH")
    return Path(executable).resolve()


def discover_ngrok(runner: CommandRunner, environment_file: Path) -> NgrokRuntime:
    if (
        environment_file.is_symlink()
        or not environment_file.is_file()
        or environment_file.stat().st_uid != os.getuid()
        or stat.S_IMODE(environment_file.stat().st_mode) != 0o600
    ):
        raise RuntimeError(f"environment file must exist, be user-owned, and mode 0600: {environment_file}")
    values = [
        line.partition("=")[2]
        for line in environment_file.read_text().splitlines()
        if line.partition("=")[0] == "OCINT_NGROK_URL"
    ]
    if len(values) != 1 or not values[0]:
        raise RuntimeError(f"OCINT_NGROK_URL must occur exactly once with a value in {environment_file}")
    return discover_ngrok_runtime(runner, values[0])


def discover_ngrok_runtime(runner: CommandRunner, url: str) -> NgrokRuntime:
    executable_name = shutil.which("ngrok")
    if executable_name is None:
        raise RuntimeError("ngrok executable is not installed on PATH")
    runtime = NgrokRuntime(executable=Path(executable_name).resolve(), version="", url=validate_ngrok_url(url))
    return validate_ngrok_runtime(runner, runtime)


def validate_ngrok_runtime(runner: CommandRunner, runtime: NgrokRuntime) -> NgrokRuntime:
    executable = runtime.executable.expanduser().resolve()
    if runtime.executable != executable or not executable.is_file() or not os.access(executable, os.X_OK):
        raise RuntimeError(f"ngrok executable must be an absolute executable regular file: {executable}")
    version = runner.run((str(executable), "version")).stdout.strip()
    if re.fullmatch(r"ngrok version 3(?:\.[0-9]+){1,2}", version) is None:
        raise RuntimeError(f"ngrok major version 3 is required; found {version or 'no version'}")
    if runtime.version and runtime.version != version:
        raise RuntimeError(f"ngrok version changed during installation: expected {runtime.version}; found {version}")
    return NgrokRuntime(executable=executable, version=version, url=validate_ngrok_url(runtime.url))


def validate_ngrok_url(value: str) -> str:
    try:
        parsed = urlparse(value)
        hostname = parsed.hostname
        port = parsed.port
    except ValueError as error:
        raise RuntimeError(
            "OCINT_NGROK_URL must be an HTTPS static hostname without userinfo, port, query, fragment, or non-root path"
        ) from error
    address = False
    if hostname is not None:
        try:
            ip_address(hostname)
            address = True
        except ValueError:
            pass
    if (
        parsed.scheme != "https"
        or hostname is None
        or parsed.username is not None
        or parsed.password is not None
        or port is not None
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/"}
        or hostname == "localhost"
        or address
        or re.fullmatch(
            r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)+",
            hostname,
        )
        is None
    ):
        raise RuntimeError(
            "OCINT_NGROK_URL must be an HTTPS static hostname without userinfo, port, query, fragment, or non-root path"
        )
    return value


def systemd_duration(seconds: int) -> str:
    return f"{seconds // 60}m" if seconds % 60 == 0 else f"{seconds}s"
