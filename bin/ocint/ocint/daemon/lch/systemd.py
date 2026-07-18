import json
import os
import platform
import shutil
import stat
import subprocess
from collections.abc import Iterator, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel, ConfigDict

from ocint.daemon.logging import DaemonLogSettings, follow_log, read_log_tail


class CommandResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    stdout: str = ""
    stderr: str = ""


class CommandRunner(Protocol):
    def run(self, arguments: Sequence[str]) -> CommandResult: ...
    def run_isolated(self, arguments: Sequence[str], environment: Mapping[str, str]) -> CommandResult: ...


class SubprocessRunner:
    def __init__(self, timeout_seconds: int = 30) -> None:
        self.timeout_seconds = timeout_seconds

    def run(self, arguments: Sequence[str]) -> CommandResult:
        environment = dict(os.environ)
        for name in ("GH_TOKEN", "GITHUB_TOKEN", "OCINT_DAEMON_API_TOKEN", "OCINT_DAEMON_GITHUB_TOKEN"):
            environment.pop(name, None)
        environment.update(self._noninteractive_environment())
        if "--follow" in arguments:
            subprocess.run(arguments, check=True, env=environment, stdin=subprocess.DEVNULL)
            return CommandResult()
        return self._run(arguments, environment)

    def run_isolated(self, arguments: Sequence[str], environment: Mapping[str, str]) -> CommandResult:
        isolated = dict(environment)
        isolated.update(self._noninteractive_environment())
        return self._run(arguments, isolated)

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


class SystemdPaths(BaseModel):
    model_config = ConfigDict(frozen=True)
    directory: Path
    environment_file: Path
    config_home: Path
    data_home: Path
    state_home: Path
    daemon_config: Path
    home: Path

    @property
    def service(self) -> Path:
        return self.directory / "ocint-daemon.service"

    @property
    def timer(self) -> Path:
        return self.directory / "ocint-daemon.timer"

    @property
    def environment_reference(self) -> str:
        return self.reference(self.environment_file)

    @property
    def daemon_log(self) -> Path:
        return self.state_home / "ocint" / "daemon.log"

    def reference(self, path: Path) -> str:
        resolved = path.resolve()
        home = self.home.resolve()
        try:
            relative = resolved.relative_to(home)
        except ValueError:
            return str(resolved)
        return f"%h/{relative.as_posix()}"


def timer_text() -> str:
    return """[Unit]
Description=Schedule ocint daemon

[Timer]
OnStartupSec=1m
OnUnitInactiveSec=15m
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


class SystemdLifecycle:
    def __init__(self, paths: SystemdPaths, runner: CommandRunner) -> None:
        self.paths = paths
        self.runner = runner

    def install(self, executable: Path) -> None:
        self.validate_host()
        executable = self.validate_executable(executable)
        self._validate_environment()
        self.validate_lingering()
        self.validate_install_paths()
        self.paths.directory.mkdir(parents=True, exist_ok=True)
        self.paths.timer.write_text(timer_text())
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
        self.runner.run(("systemctl", "--user", "daemon-reload"))
        self.runner.run(("systemctl", "--user", "enable", "--now", "ocint-daemon.timer"))

    def uninstall(self) -> None:
        self.runner.run(("systemctl", "--user", "disable", "--now", "ocint-daemon.timer"))
        self.runner.run(("systemctl", "--user", "stop", "ocint-daemon.service"))
        self.paths.timer.unlink(missing_ok=True)
        self.paths.service.unlink(missing_ok=True)
        self.runner.run(("systemctl", "--user", "daemon-reload"))

    def status(self) -> str:
        installed = self.paths.timer.is_file() and self.paths.service.is_file()
        if not installed:
            return f"installed: no\nlog: {self.paths.daemon_log}"
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
        timer_state = " ".join(filter(None, (timer.get("ActiveState", "unknown"), timer.get("SubState", ""))))
        service_state = " ".join(filter(None, (service.get("ActiveState", "unknown"), service.get("SubState", ""))))
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
        return "\n".join(
            (
                "installed: yes",
                f"timer: {timer_state}",
                f"last trigger: {last_trigger}",
                f"next trigger: {next_trigger}",
                f"service: {service_state}",
                f"last result: {service.get('Result', 'unknown') or 'unknown'}",
                f"last exit status: {service.get('ExecMainStatus', 'unknown') or 'unknown'}",
                f"last started: {service.get('ExecMainStartTimestamp', 'unavailable') or 'unavailable'}",
                f"last completed: {service.get('ExecMainExitTimestamp', 'unavailable') or 'unavailable'}",
                f"log: {self.paths.daemon_log}",
            )
        )

    def logs(self, lines: int) -> str:
        return read_log_tail(DaemonLogSettings(path=self.paths.daemon_log), lines)

    def follow_logs(self, lines: int) -> Iterator[str]:
        return follow_log(DaemonLogSettings(path=self.paths.daemon_log), lines)

    def _unit_properties(self, unit: str, names: tuple[str, ...]) -> dict[str, str]:
        result = self.runner.run(
            ("systemctl", "--user", "show", unit, *(f"--property={name}" for name in names))
        ).stdout
        return dict(line.partition("=")[::2] for line in result.splitlines() if "=" in line)

    @staticmethod
    def _timestamp(microseconds: int) -> str:
        return datetime.fromtimestamp(microseconds / 1_000_000, UTC).isoformat().replace("+00:00", "Z")

    def _validate_environment(self) -> None:
        path = self.paths.environment_file
        if not path.is_file() or path.stat().st_uid != os.getuid() or stat.S_IMODE(path.stat().st_mode) != 0o600:
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
        required = {"provision", "install", "uninstall", "status", "logs"}
        if not required.issubset(lch_commands):
            raise RuntimeError(f"ocint executable does not expose the required daemon lch commands: {resolved}")
        return resolved

    def validate_host(self) -> None:
        if platform.system() != "Linux":
            raise RuntimeError("ocint daemon lch requires Linux")

    def validate_lingering(self) -> None:
        user = os.environ.get("USER", "")
        lingering = self.runner.run(("loginctl", "show-user", user, "--property=Linger", "--value")).stdout.strip()
        if lingering != "yes":
            raise RuntimeError('user lingering is disabled; run loginctl enable-linger "$USER"')

    def validate_install_paths(self) -> None:
        if self.paths.directory.is_symlink() or (self.paths.directory.exists() and not self.paths.directory.is_dir()):
            raise RuntimeError(f"systemd user directory must be a regular directory: {self.paths.directory}")
        for path in (self.paths.timer, self.paths.service):
            if path.is_symlink() or (path.exists() and (not path.is_file() or path.stat().st_uid != os.getuid())):
                raise RuntimeError(f"generated unit path must be a regular file: {path}")


def installed_ocint() -> Path:
    executable = shutil.which("ocint")
    if executable is None:
        raise RuntimeError("ocint executable is not installed on PATH")
    return Path(executable).resolve()
