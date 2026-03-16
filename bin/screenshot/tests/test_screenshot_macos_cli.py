import json
from pathlib import Path

from click.testing import CliRunner


def write_config(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload))
    return path


def test_apply_macos_screenshot_location_creates_directory_and_runs_defaults(tmp_path, monkeypatch):
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
    monkeypatch.setattr("screenshot.macos.sys.platform", "darwin")

    from screenshot.macos import apply_macos_screenshot_location

    calls: list[list[str]] = []

    def fake_run(command: list[str], *, check: bool, text: bool) -> None:
        assert check is True
        assert text is True
        calls.append(command)

    monkeypatch.setattr("screenshot.macos.subprocess.run", fake_run)

    result = apply_macos_screenshot_location(config_file=config_file)

    expected_dir = tmp_path / "Desktop/Screenshots"
    assert result == expected_dir.resolve()
    assert expected_dir.is_dir()
    assert calls == [
        ["defaults", "write", "com.apple.screencapture", "location", str(expected_dir.resolve())],
        ["killall", "SystemUIServer"],
    ]


def test_macos_apply_command_exits_cleanly_with_applied_path(monkeypatch, tmp_path):
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
    monkeypatch.setenv("SCREENSHOT_CONFIG_FILE", str(config_file))

    import screenshot.cli as cli_module

    applied_path = tmp_path / "Desktop/Screenshots"
    monkeypatch.setattr(cli_module, "apply_macos_screenshot_location", lambda: applied_path)

    runner = CliRunner()
    result = runner.invoke(cli_module.main, ["macos", "apply"])

    assert result.exit_code == 0
    assert result.output.splitlines() == [str(applied_path)]


def test_macos_apply_command_surfaces_non_macos_error(monkeypatch):
    import screenshot.cli as cli_module

    monkeypatch.setattr(
        cli_module,
        "apply_macos_screenshot_location",
        lambda: (_ for _ in ()).throw(RuntimeError("macOS screenshot settings can only be applied on macOS")),
    )

    runner = CliRunner()
    result = runner.invoke(cli_module.main, ["macos", "apply"])

    assert result.exit_code != 0
    assert "macOS screenshot settings can only be applied on macOS" in result.output
