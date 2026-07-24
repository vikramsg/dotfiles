import json
import stat
import subprocess
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

import pytest
from ocint.daemon.config import LifecycleConfig, LoggingConfig
from ocint.daemon.lch import SubprocessRunner, SystemdLifecycle, SystemdPaths, service_text, timer_text
from ocint.daemon.lch.systemd import CommandResult
from ocint.daemon.logging import daemon_log_settings


@dataclass
class FakeRunner:
    compatible: bool = True
    calls: list[list[str]] = field(default_factory=list)

    def run(self, arguments: Sequence[str]) -> CommandResult:
        command = list(arguments)
        self.calls.append(command)
        if command[-2:] == ["daemon", "--help"]:
            commands = "  run\n  doctor\n  lch\n" if self.compatible else "  config\n"
            return CommandResult(stdout=f"Commands:\n{commands}")
        if command[-3:] == ["daemon", "lch", "--help"]:
            return CommandResult(
                stdout="Commands:\n  apply\n  attach\n  lifecycle\n  list\n  logs\n  setup\n  status\n  uninstall\n"
            )
        if command[0] == "loginctl":
            return CommandResult(stdout="yes\n")
        return CommandResult()

    def run_isolated(self, arguments: Sequence[str], environment: Mapping[str, str]) -> CommandResult:
        _ = environment
        return self.run(arguments)

    def run_interactive(self, arguments: Sequence[str], environment: Mapping[str, str]) -> None:
        _ = (arguments, environment)
        raise AssertionError("not used")


@dataclass
class StatusRunner:
    def run(self, arguments: Sequence[str]) -> CommandResult:
        command = list(arguments)
        if "list-timers" in command:
            return CommandResult(
                stdout='[{"next":1784312702000000,"left":1,"last":1784311708000000,'
                '"passed":1,"unit":"ocint-daemon.timer","activates":"ocint-daemon.service"}]'
            )
        if "ocint-daemon.timer" in command:
            return CommandResult(
                stdout="ActiveState=active\nSubState=waiting\nLastTriggerUSec=Fri 2026-07-17 18:08:28 UTC\n"
            )
        if "ocint-daemon.service" in command:
            return CommandResult(
                stdout=(
                    "ActiveState=inactive\nSubState=dead\nResult=success\nExecMainStatus=0\n"
                    "ExecMainStartTimestamp=Fri 2026-07-17 18:08:28 UTC\n"
                    "ExecMainExitTimestamp=Fri 2026-07-17 18:10:02 UTC\n"
                )
            )
        raise AssertionError(command)

    def run_isolated(self, arguments: Sequence[str], environment: Mapping[str, str]) -> CommandResult:
        _ = (arguments, environment)
        raise AssertionError("not used")

    def run_interactive(self, arguments: Sequence[str], environment: Mapping[str, str]) -> None:
        _ = (arguments, environment)
        raise AssertionError("not used")


def test_generated_timer_has_bounded_schedule() -> None:
    # GIVEN / WHEN
    rendered = timer_text(LifecycleConfig())

    # THEN
    assert "OnStartupSec=1m" in rendered
    assert "OnUnitInactiveSec=10m" in rendered
    assert "Unit=ocint-daemon.service" in rendered


def test_generated_timer_uses_supplied_lifecycle_policy() -> None:
    # GIVEN
    config = LifecycleConfig(startup_delay_seconds=75, inactive_interval_seconds=901)

    # WHEN
    rendered = timer_text(config)

    # THEN
    assert "OnStartupSec=75s" in rendered
    assert "OnUnitInactiveSec=901s" in rendered


def test_lifecycle_reads_provisioned_api_token_from_private_environment(tmp_path: Path) -> None:
    # GIVEN
    environment = tmp_path / "daemon.env"
    environment.write_text("OCINT_DAEMON_API_TOKEN=local-api-token\nOCINT_DAEMON_GITHUB_TOKEN=github-token\n")
    environment.chmod(0o600)
    paths = SystemdPaths(
        directory=tmp_path / "systemd",
        environment_file=environment,
        config_home=tmp_path / "config",
        data_home=tmp_path / "data",
        state_home=tmp_path / "state",
        daemon_config=tmp_path / "daemon.toml",
        home=tmp_path,
    )

    # WHEN
    token = SystemdLifecycle(paths, FakeRunner()).api_token()

    # THEN
    assert token == "local-api-token"


def test_generated_service_is_one_oneshot_cycle() -> None:
    # GIVEN / WHEN
    rendered = service_text(
        Path("/opt/ocint/bin/ocint"),
        "%h/.config/ocint/daemon.env",
        "%h/.config",
        "%h/.local/share",
        "%h/.local/state",
        "%h/.config/ocint/daemon.toml",
    )

    # THEN
    assert "Type=oneshot" in rendered
    assert "UMask=0077" in rendered
    assert "EnvironmentFile=%h/.config/ocint/daemon.env" in rendered
    assert "Environment=XDG_CONFIG_HOME=%h/.config" in rendered
    assert "Environment=XDG_DATA_HOME=%h/.local/share" in rendered
    assert "Environment=XDG_STATE_HOME=%h/.local/state" in rendered
    assert "Environment=OCINT_DAEMON_CONFIG=%h/.config/ocint/daemon.toml" in rendered
    assert "ExecStart=/opt/ocint/bin/ocint daemon run" in rendered
    assert "TimeoutStartSec=infinity" in rendered


def test_install_validates_exact_executable_and_wires_custom_xdg_environment(tmp_path: Path) -> None:
    # GIVEN
    home = tmp_path / "home"
    environment = home / "xdg" / "ocint" / "daemon.env"
    environment.parent.mkdir(parents=True)
    environment.write_text("OCINT_DAEMON_API_TOKEN=token\n")
    environment.chmod(0o600)
    executable = tmp_path / "installed" / "ocint"
    executable.parent.mkdir()
    executable.write_text("#!/bin/sh\nexit 0\n")
    executable.chmod(0o755)
    config_home = home / "xdg"
    data_home = home / "data"
    state_home = home / "state"
    paths = SystemdPaths(
        directory=config_home / "systemd" / "user",
        environment_file=environment,
        config_home=config_home,
        data_home=data_home,
        state_home=state_home,
        daemon_config=config_home / "ocint" / "daemon.toml",
        home=home,
    )
    runner = FakeRunner()
    lifecycle = SystemdLifecycle(paths, runner)

    # WHEN
    lifecycle.install(executable, LifecycleConfig())

    # THEN
    assert runner.calls[0] == [str(executable.resolve()), "daemon", "--help"]
    assert runner.calls[1] == [str(executable.resolve()), "daemon", "lch", "--help"]
    assert runner.calls[-2:] == [
        ["systemctl", "--user", "daemon-reload"],
        ["systemctl", "--user", "enable", "--now", "ocint-daemon.timer"],
    ]
    assert "EnvironmentFile=%h/xdg/ocint/daemon.env" in paths.service.read_text()
    assert "Environment=XDG_CONFIG_HOME=%h/xdg" in paths.service.read_text()
    assert "Environment=XDG_DATA_HOME=%h/data" in paths.service.read_text()
    assert "Environment=XDG_STATE_HOME=%h/state" in paths.service.read_text()
    assert "Environment=OCINT_DAEMON_CONFIG=%h/xdg/ocint/daemon.toml" in paths.service.read_text()
    assert f"ExecStart={executable.resolve()} daemon run" in paths.service.read_text()
    assert paths.timer.read_text() == timer_text(LifecycleConfig())
    assert stat.S_IMODE(paths.service.stat().st_mode) == 0o644
    assert stat.S_IMODE(paths.timer.stat().st_mode) == 0o644


def test_incompatible_path_executable_fails_before_unit_writes(tmp_path: Path) -> None:
    # GIVEN
    executable = tmp_path / "ocint"
    executable.write_text("#!/bin/sh\nexit 0\n")
    executable.chmod(0o755)
    home = tmp_path / "home"
    paths = SystemdPaths(
        directory=home / ".config" / "systemd" / "user",
        environment_file=home / ".config" / "ocint" / "daemon.env",
        config_home=home / ".config",
        data_home=home / ".local" / "share",
        state_home=home / ".local" / "state",
        daemon_config=home / ".config" / "ocint" / "daemon.toml",
        home=home,
    )
    lifecycle = SystemdLifecycle(paths, FakeRunner(compatible=False))

    # WHEN / THEN
    with pytest.raises(RuntimeError, match="does not expose daemon run, doctor, and lch"):
        lifecycle.install(executable, LifecycleConfig())
    assert not paths.directory.exists()


def test_subprocess_runner_is_bounded_noninteractive_and_pager_free() -> None:
    # GIVEN
    runner = SubprocessRunner(timeout_seconds=1)
    command = (
        sys.executable,
        "-c",
        "import json, os, sys; print(json.dumps({'stdin': sys.stdin.read(), 'env': dict(os.environ)}))",
    )

    # WHEN
    result = runner.run_isolated(command, {"PATH": "/usr/bin", "RECOGNIZABLE": "present"})
    payload = json.loads(result.stdout)

    # THEN
    assert payload["stdin"] == ""
    assert payload["env"]["PAGER"] == "cat"
    assert payload["env"]["GH_PAGER"] == "cat"
    assert payload["env"]["GIT_PAGER"] == "cat"
    assert payload["env"]["GIT_TERMINAL_PROMPT"] == "0"
    assert payload["env"]["GH_PROMPT_DISABLED"] == "1"
    assert payload["env"]["RECOGNIZABLE"] == "present"


def test_subprocess_runner_enforces_timeout() -> None:
    # GIVEN
    runner = SubprocessRunner(timeout_seconds=1)

    # WHEN / THEN
    with pytest.raises(subprocess.TimeoutExpired):
        runner.run_isolated((sys.executable, "-c", "import time; time.sleep(2)"), {"PATH": "/usr/bin"})


def test_status_reports_timer_schedule_service_result_and_log_path(tmp_path: Path) -> None:
    # GIVEN
    home = tmp_path / "home"
    paths = SystemdPaths(
        directory=home / ".config" / "systemd" / "user",
        environment_file=home / ".config" / "ocint" / "daemon.env",
        config_home=home / ".config",
        data_home=home / ".local" / "share",
        state_home=home / ".local" / "state",
        daemon_config=home / ".config" / "ocint" / "daemon.toml",
        home=home,
    )
    paths.directory.mkdir(parents=True)
    paths.timer.write_text("")
    paths.service.write_text("")
    lifecycle = SystemdLifecycle(paths, StatusRunner())

    # WHEN
    status = lifecycle.status(daemon_log_settings(paths.state_home, LoggingConfig()).path)

    # THEN
    assert status.installed
    assert status.timer_state == "active"
    assert status.timer_substate == "waiting"
    assert status.last_trigger == "2026-07-17 18:08:28 UTC"
    assert status.next_trigger == "2026-07-17 18:25:02 UTC"
    assert status.service_state == "inactive"
    assert status.service_substate == "dead"
    assert status.last_result == "success"
    assert status.last_exit_status == "0"
    assert status.log_path == daemon_log_settings(paths.state_home, LoggingConfig()).path
