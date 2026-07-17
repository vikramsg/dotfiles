import stat
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

import pytest
from ocint.daemon.lch import SystemdLifecycle, SystemdPaths, service_text, timer_text
from ocint.daemon.lch.systemd import CommandResult


@dataclass
class FakeRunner:
    compatible: bool = True
    calls: list[list[str]] = field(default_factory=list)

    def run(self, arguments: Sequence[str]) -> CommandResult:
        command = list(arguments)
        self.calls.append(command)
        if command[-2:] == ["daemon", "--help"]:
            commands = "  run\n  lch\n" if self.compatible else "  config\n"
            return CommandResult(stdout=f"Commands:\n{commands}")
        if command[-3:] == ["daemon", "lch", "--help"]:
            return CommandResult(stdout="Commands:\n  provision\n  install\n  uninstall\n  status\n  logs\n")
        if command[0] == "loginctl":
            return CommandResult(stdout="yes\n")
        return CommandResult()


def test_generated_timer_has_bounded_schedule() -> None:
    # GIVEN / WHEN
    rendered = timer_text()

    # THEN
    assert "OnStartupSec=1m" in rendered
    assert "OnUnitInactiveSec=15m" in rendered
    assert "Unit=ocint-daemon.service" in rendered


def test_generated_service_is_one_oneshot_cycle() -> None:
    # GIVEN / WHEN
    rendered = service_text(
        Path("/opt/ocint/bin/ocint"),
        "%h/.config/ocint/daemon.env",
        "%h/.config",
        "%h/.local/share",
        "%h/.config/ocint/daemon.toml",
    )

    # THEN
    assert "Type=oneshot" in rendered
    assert "UMask=0077" in rendered
    assert "EnvironmentFile=%h/.config/ocint/daemon.env" in rendered
    assert "Environment=XDG_CONFIG_HOME=%h/.config" in rendered
    assert "Environment=XDG_DATA_HOME=%h/.local/share" in rendered
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
    paths = SystemdPaths(
        directory=config_home / "systemd" / "user",
        environment_file=environment,
        config_home=config_home,
        data_home=data_home,
        daemon_config=config_home / "ocint" / "daemon.toml",
        home=home,
    )
    runner = FakeRunner()
    lifecycle = SystemdLifecycle(paths, runner)

    # WHEN
    lifecycle.install(executable)

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
    assert "Environment=OCINT_DAEMON_CONFIG=%h/xdg/ocint/daemon.toml" in paths.service.read_text()
    assert f"ExecStart={executable.resolve()} daemon run" in paths.service.read_text()
    assert paths.timer.read_text() == timer_text()
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
        daemon_config=home / ".config" / "ocint" / "daemon.toml",
        home=home,
    )
    lifecycle = SystemdLifecycle(paths, FakeRunner(compatible=False))

    # WHEN / THEN
    with pytest.raises(RuntimeError, match="does not expose daemon run and lch"):
        lifecycle.install(executable)
    assert not paths.directory.exists()
