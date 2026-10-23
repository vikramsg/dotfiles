import json
import stat
import subprocess
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

import pytest
from ocint.daemon.config import LifecycleConfig, LoggingConfig
from ocint.daemon.lch import (
    NgrokRuntime,
    SubprocessRunner,
    SystemdLifecycle,
    SystemdPaths,
    coordinator_ngrok_command,
    coordinator_ngrok_service_text,
    coordinator_service_text,
    service_text,
    timer_text,
)
from ocint.daemon.lch.systemd import CommandResult, validate_ngrok_url
from ocint.daemon.logging import daemon_log_settings


@dataclass
class FakeRunner:
    compatible: bool = True
    coordinator_unit_state: str = "disabled"
    ngrok_unit_state: str = "disabled"
    calls: list[list[str]] = field(default_factory=list)

    def run(self, arguments: Sequence[str]) -> CommandResult:
        command = list(arguments)
        self.calls.append(command)
        if command[-2:] == ["daemon", "--help"]:
            commands = "  run\n  doctor\n  lch\n" if self.compatible else "  config\n"
            return CommandResult(stdout=f"Commands:\n{commands}")
        if command[-3:] == ["daemon", "lch", "--help"]:
            return CommandResult(
                stdout="Commands:\n  apply\n  attach\n  lifecycle\n  list\n  logs\n  setup\n  slack-token\n  status\n  uninstall\n"
            )
        if command[0] == "loginctl":
            return CommandResult(stdout="yes\n")
        if command[-1] == "version":
            return CommandResult(stdout="ngrok version 3.31.0\n")
        if "ocint-coordinator-ngrok.service" in command and "--property=UnitFileState" in command:
            return CommandResult(stdout=f"UnitFileState={self.ngrok_unit_state}\n")
        if "ocint-coordinator.service" in command and "--property=UnitFileState" in command:
            return CommandResult(stdout=f"UnitFileState={self.coordinator_unit_state}\n")
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
        if "ocint-coordinator-ngrok.service" in command:
            return CommandResult(stdout="ActiveState=inactive\nSubState=dead\nUnitFileState=disabled\n")
        if "ocint-coordinator.service" in command:
            return CommandResult(stdout="ActiveState=active\nSubState=running\nUnitFileState=enabled\n")
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


def test_generated_coordinator_units_are_private_restartable_and_expose_only_ingress() -> None:
    # GIVEN
    runtime = NgrokRuntime(
        executable=Path("/opt/ngrok/bin/ngrok"),
        version="ngrok version 3.31.0",
        url="https://static.example.test",
    )

    # WHEN
    coordinator = coordinator_service_text(
        Path("/opt/ocint/bin/ocint"),
        "%h/.config/ocint/daemon.env",
        "%h/.config",
        "%h/.local/share",
        "%h/.local/state",
        "%h/.config/ocint/daemon.toml",
    )
    ngrok = coordinator_ngrok_service_text(runtime, "%h", "%h/.config", "C.UTF-8", 8733)

    # THEN
    assert (
        coordinator
        == """[Unit]
Description=Run the ocint Slack coordinator
Wants=network-online.target
After=network-online.target

[Service]
Type=simple
UMask=0077
KillMode=mixed
EnvironmentFile=%h/.config/ocint/daemon.env
Environment=XDG_CONFIG_HOME=%h/.config
Environment=XDG_DATA_HOME=%h/.local/share
Environment=XDG_STATE_HOME=%h/.local/state
Environment=OCINT_DAEMON_CONFIG=%h/.config/ocint/daemon.toml
ExecStart=/opt/ocint/bin/ocint daemon coordinator run
Restart=on-failure
RestartSec=5s

[Install]
WantedBy=default.target
"""
    )
    assert "Requires=ocint-coordinator.service" in ngrok
    assert "After=network-online.target ocint-coordinator.service" in ngrok
    assert "EnvironmentFile=" not in ngrok
    assert "ExecStart=/usr/bin/env -i HOME=%h XDG_CONFIG_HOME=%h/.config LANG=C.UTF-8" in ngrok
    assert "/opt/ngrok/bin/ngrok http --url=https://static.example.test" in ngrok
    assert "--inspect=false" in ngrok
    assert "127.0.0.1:8733" in ngrok
    assert all(str(port) not in ngrok for port in (8732, 4098, 4040))


def test_ngrok_command_clears_daemon_credentials_from_the_final_environment(tmp_path: Path) -> None:
    # GIVEN
    executable = tmp_path / "ngrok"
    executable.write_text("#!/bin/sh\n/usr/bin/env\n")
    executable.chmod(0o755)
    runtime = NgrokRuntime(
        executable=executable.resolve(),
        version="ngrok version 3.31.0",
        url="https://static.example.test",
    )
    command = coordinator_ngrok_command(runtime, str(tmp_path), str(tmp_path / "config"), "C.UTF-8", 8733)

    # WHEN
    result = subprocess.run(
        command,
        check=True,
        capture_output=True,
        text=True,
        env={
            "OCINT_DAEMON_SLACK_SIGNING_SECRET": "must-not-leak",
            "OCINT_DAEMON_GITHUB_TOKEN": "must-not-leak",
            "OCINT_DAEMON_API_TOKEN": "must-not-leak",
        },
    )

    # THEN
    final_environment = dict(line.partition("=")[::2] for line in result.stdout.splitlines())
    assert {name: final_environment[name] for name in ("HOME", "XDG_CONFIG_HOME", "LANG")} == {
        "HOME": str(tmp_path),
        "XDG_CONFIG_HOME": str(tmp_path / "config"),
        "LANG": "C.UTF-8",
    }
    assert set(final_environment) <= {"HOME", "XDG_CONFIG_HOME", "LANG", "PWD"}
    assert not any(name.startswith("OCINT_") for name in final_environment)


@pytest.mark.parametrize(
    "value",
    [
        "http://static.example.test",
        "https://user@static.example.test",
        "https://static.example.test/events",
        "https://static.example.test?token=value",
        "https://static.example.test#fragment",
        "https://127.0.0.1",
        "https://localhost",
    ],
)
def test_ngrok_url_rejects_nonstatic_or_nonroot_endpoints(value: str) -> None:
    # GIVEN / WHEN / THEN
    with pytest.raises(RuntimeError, match="HTTPS static hostname"):
        validate_ngrok_url(value)


@pytest.mark.parametrize(
    ("coordinator_state", "ngrok_state"),
    [("disabled", "disabled"), ("enabled", "enabled")],
)
def test_install_preserves_and_reports_coordinator_enablement_while_wiring_custom_xdg_environment(
    tmp_path: Path,
    coordinator_state: str,
    ngrok_state: str,
) -> None:
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
    runner = FakeRunner(coordinator_unit_state=coordinator_state, ngrok_unit_state=ngrok_state)
    lifecycle = SystemdLifecycle(paths, runner)
    ngrok = tmp_path / "installed" / "ngrok"
    ngrok.write_text("#!/bin/sh\nexit 0\n")
    ngrok.chmod(0o755)
    runtime = NgrokRuntime(
        executable=ngrok.resolve(),
        version="ngrok version 3.31.0",
        url="https://static.example.test",
    )

    # WHEN
    enablement = lifecycle.install(executable, LifecycleConfig(), 8733, runtime)

    # THEN
    assert runner.calls[0] == [str(executable.resolve()), "daemon", "--help"]
    assert runner.calls[1] == [str(executable.resolve()), "daemon", "lch", "--help"]
    assert runner.calls[-4:-2] == [
        ["systemctl", "--user", "daemon-reload"],
        ["systemctl", "--user", "enable", "--now", "ocint-daemon.timer"],
    ]
    assert enablement.coordinator == coordinator_state
    assert enablement.ngrok == ngrok_state
    assert not any(
        "ocint-coordinator" in " ".join(command) and ("enable" in command or "disable" in command)
        for command in runner.calls
    )
    assert "EnvironmentFile=%h/xdg/ocint/daemon.env" in paths.service.read_text()
    assert "Environment=XDG_CONFIG_HOME=%h/xdg" in paths.service.read_text()
    assert "Environment=XDG_DATA_HOME=%h/data" in paths.service.read_text()
    assert "Environment=XDG_STATE_HOME=%h/state" in paths.service.read_text()
    assert "Environment=OCINT_DAEMON_CONFIG=%h/xdg/ocint/daemon.toml" in paths.service.read_text()
    assert f"ExecStart={executable.resolve()} daemon run" in paths.service.read_text()
    assert paths.timer.read_text() == timer_text(LifecycleConfig())
    assert paths.coordinator_service.read_text() == coordinator_service_text(
        executable.resolve(),
        paths.environment_reference,
        paths.reference(config_home),
        paths.reference(data_home),
        paths.reference(state_home),
        paths.reference(paths.daemon_config),
    )
    assert paths.coordinator_ngrok_service.read_text() == coordinator_ngrok_service_text(
        runtime,
        paths.reference(home),
        paths.reference(config_home),
        "C.UTF-8",
        8733,
    )
    assert stat.S_IMODE(paths.service.stat().st_mode) == 0o644
    assert stat.S_IMODE(paths.timer.stat().st_mode) == 0o644
    assert stat.S_IMODE(paths.coordinator_service.stat().st_mode) == 0o644
    assert stat.S_IMODE(paths.coordinator_ngrok_service.stat().st_mode) == 0o644


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
    ngrok = tmp_path / "ngrok"
    ngrok.write_text("#!/bin/sh\nexit 0\n")
    ngrok.chmod(0o755)
    runtime = NgrokRuntime(
        executable=ngrok.resolve(),
        version="ngrok version 3.31.0",
        url="https://static.example.test",
    )

    # WHEN / THEN
    with pytest.raises(RuntimeError, match="does not expose daemon run, doctor, and lch"):
        lifecycle.install(executable, LifecycleConfig(), 8733, runtime)
    assert not paths.directory.exists()


def test_subprocess_runner_is_bounded_noninteractive_pager_free_and_scrubs_actor_token() -> None:
    # GIVEN
    runner = SubprocessRunner(timeout_seconds=1)
    command = (
        sys.executable,
        "-c",
        "import json, os, sys; print(json.dumps({'stdin': sys.stdin.read(), 'env': dict(os.environ)}))",
    )

    # WHEN
    result = runner.run_isolated(
        command,
        {
            "PATH": "/usr/bin",
            "RECOGNIZABLE": "present",
            "OCINT_E2E_SLACK_ACTOR_USER_TOKEN": "xoxp-sentinel",
        },
    )
    payload = json.loads(result.stdout)

    # THEN
    assert payload["stdin"] == ""
    assert payload["env"]["PAGER"] == "cat"
    assert payload["env"]["GH_PAGER"] == "cat"
    assert payload["env"]["GIT_PAGER"] == "cat"
    assert payload["env"]["GIT_TERMINAL_PROMPT"] == "0"
    assert payload["env"]["GH_PROMPT_DISABLED"] == "1"
    assert payload["env"]["RECOGNIZABLE"] == "present"
    assert "OCINT_E2E_SLACK_ACTOR_USER_TOKEN" not in payload["env"]


def test_subprocess_runner_scrubs_inherited_actor_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # GIVEN
    monkeypatch.setenv("OCINT_E2E_SLACK_ACTOR_USER_TOKEN", "xoxp-inherited-sentinel")
    runner = SubprocessRunner(timeout_seconds=1)

    # WHEN
    result = runner.run(
        (
            sys.executable,
            "-c",
            "import os; print(os.environ.get('OCINT_E2E_SLACK_ACTOR_USER_TOKEN', 'absent'))",
        )
    )

    # THEN
    assert result.stdout.strip() == "absent"


def test_interactive_subprocess_runner_scrubs_actor_token(tmp_path: Path) -> None:
    # GIVEN
    destination = tmp_path / "observed-token"
    runner = SubprocessRunner(timeout_seconds=1)

    # WHEN
    runner.run_interactive(
        (
            sys.executable,
            "-c",
            "import os, pathlib, sys; pathlib.Path(sys.argv[1]).write_text("
            "os.environ.get('OCINT_E2E_SLACK_ACTOR_USER_TOKEN', 'absent'))",
            str(destination),
        ),
        {"OCINT_E2E_SLACK_ACTOR_USER_TOKEN": "xoxp-interactive-sentinel"},
    )

    # THEN
    assert destination.read_text() == "absent"


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
    paths.coordinator_service.write_text("")
    paths.coordinator_ngrok_service.write_text("")
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
    assert status.coordinator_state == "active"
    assert status.coordinator_substate == "running"
    assert status.coordinator_unit_state == "enabled"
    assert status.ngrok_state == "inactive"
    assert status.ngrok_substate == "dead"
    assert status.ngrok_unit_state == "disabled"
    assert status.log_path == daemon_log_settings(paths.state_home, LoggingConfig()).path


def test_uninstall_removes_only_units_and_preserves_managed_state(tmp_path: Path) -> None:
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
    for unit in (paths.timer, paths.service, paths.coordinator_service, paths.coordinator_ngrok_service):
        unit.write_text("managed unit")
    paths.environment_file.parent.mkdir(parents=True, exist_ok=True)
    paths.environment_file.write_text("OCINT_DAEMON_API_TOKEN=preserved\n")
    paths.daemon_config.write_text("preserved config")
    workspace = paths.data_home / "ocint" / "coordinator"
    workspace.mkdir(parents=True)
    (workspace / "repositories.json").write_text("preserved workspace")
    state = paths.state_home / "ocint" / "preserved-state"
    state.parent.mkdir(parents=True)
    state.write_text("preserved database state")
    opencode_data = paths.data_home / "ocint" / "coordinator-opencode-data" / "opencode" / "state"
    opencode_data.parent.mkdir(parents=True)
    opencode_data.write_text("preserved OpenCode data")
    runner = FakeRunner()

    # WHEN
    SystemdLifecycle(paths, runner).uninstall()

    # THEN
    assert all(
        not unit.exists()
        for unit in (paths.timer, paths.service, paths.coordinator_service, paths.coordinator_ngrok_service)
    )
    assert paths.environment_file.read_text() == "OCINT_DAEMON_API_TOKEN=preserved\n"
    assert paths.daemon_config.read_text() == "preserved config"
    assert (workspace / "repositories.json").read_text() == "preserved workspace"
    assert state.read_text() == "preserved database state"
    assert opencode_data.read_text() == "preserved OpenCode data"
    assert runner.calls[:3] == [
        ["systemctl", "--user", "disable", "--now", "ocint-coordinator-ngrok.service"],
        ["systemctl", "--user", "disable", "--now", "ocint-coordinator.service"],
        ["systemctl", "--user", "disable", "--now", "ocint-daemon.timer"],
    ]
