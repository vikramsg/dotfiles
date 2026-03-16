import json
from pathlib import Path

from click.testing import CliRunner


def write_config(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload))
    return path


def test_apply_linux_watcher_writes_systemd_units_and_enables_path(tmp_path, monkeypatch):
    config_file = write_config(
        tmp_path / ".config/screenshot/config.json",
        {
            "screenshot_dir": "~/Desktop/Screenshots",
            "sync": {
                "vm_host": "test-vm",
                "remote_dir": "~/Desktop/Screenshots/",
            },
        },
    )
    monkeypatch.setenv("HOME", str(tmp_path))

    import screenshot.systemd as systemd_module

    calls: list[list[str]] = []

    def fake_run(command: list[str], *, check: bool, text: bool) -> None:
        assert check is True
        assert text is True
        calls.append(command)

    monkeypatch.setattr(systemd_module.subprocess, "run", fake_run)

    watch_path = systemd_module.apply_linux_screenshot_watcher(config_file=config_file)

    expected_watch_path = (tmp_path / "Desktop/Screenshots").resolve()
    service_path = tmp_path / ".config/systemd/user/screenshot-clipboard.service"
    unit_path = tmp_path / ".config/systemd/user/screenshot-clipboard.path"

    assert watch_path == expected_watch_path
    assert expected_watch_path.is_dir()
    assert service_path.exists()
    assert unit_path.exists()
    assert "ExecStart=" in service_path.read_text()
    assert f"PathModified={expected_watch_path}" in unit_path.read_text()
    assert calls == [
        ["systemctl", "--user", "daemon-reload"],
        ["systemctl", "--user", "enable", "--now", "screenshot-clipboard.path"],
        ["systemctl", "--user", "start", "screenshot-clipboard.service"],
    ]


def test_systemd_apply_command_exits_cleanly_with_applied_path(monkeypatch, tmp_path):
    import screenshot.cli as cli_module

    applied_path = tmp_path / "Desktop/Screenshots"
    monkeypatch.setattr(cli_module, "apply_linux_screenshot_watcher", lambda: applied_path)

    runner = CliRunner()
    result = runner.invoke(cli_module.main, ["systemd", "apply"])

    assert result.exit_code == 0
    assert result.output.splitlines() == [str(applied_path)]


def test_systemd_apply_command_surfaces_non_linux_error(monkeypatch):
    import screenshot.cli as cli_module

    monkeypatch.setattr(
        cli_module,
        "apply_linux_screenshot_watcher",
        lambda: (_ for _ in ()).throw(RuntimeError("Linux systemd user units can only be applied on Linux")),
    )

    runner = CliRunner()
    result = runner.invoke(cli_module.main, ["systemd", "apply"])

    assert result.exit_code != 0
    assert "Linux systemd user units can only be applied on Linux" in result.output
