import json
from pathlib import Path

from click.testing import CliRunner

from screenshot.config import DEFAULT_FILENAME_PATTERNS, ScreenshotConfig, SyncConfig


def build_config(screenshot_dir: Path) -> ScreenshotConfig:
    return ScreenshotConfig(
        screenshot_dir=screenshot_dir,
        clipboard_history_limit=5,
        filename_patterns=DEFAULT_FILENAME_PATTERNS,
        sync=SyncConfig(vm_host="", remote_dir=""),
    )


def test_clipboard_copy_command_succeeds_when_clipboard_backend_missing(tmp_path, monkeypatch):
    state_file = tmp_path / "history.json"
    monkeypatch.setenv("HOME", str(tmp_path))
    state_file.write_text(json.dumps({"history": [str((tmp_path / "Screenshots/shot 1.png").resolve())]}))
    monkeypatch.setenv("SCREENSHOT_STATE_FILE", str(state_file))

    import screenshot.clipboard as clipboard_module
    import screenshot.cli as cli_module

    def fake_run(command: list[str], **_kwargs) -> None:
        raise FileNotFoundError(command[0])

    monkeypatch.setattr(clipboard_module.subprocess, "run", fake_run)

    runner = CliRunner()
    result = runner.invoke(cli_module.main, ["clipboard", "copy", "--index", "1"])

    assert result.exit_code == 0
    assert result.output.splitlines() == [r"~/Screenshots/shot\ 1.png"]


def test_on_event_updates_history_when_clipboard_backend_missing(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    screenshot_dir = tmp_path / "Screenshots"
    screenshot_dir.mkdir(parents=True, exist_ok=True)
    newest = screenshot_dir / "Screenshot 2026-03-16 at 9.01.00 AM.png"
    newest.write_text("img")

    import screenshot.clipboard as clipboard_module
    from screenshot.clipboard import handle_event
    from screenshot.state import load_history_state

    def fake_run(command: list[str], **_kwargs) -> None:
        raise FileNotFoundError(command[0])

    monkeypatch.setattr(clipboard_module.subprocess, "run", fake_run)

    state_file = tmp_path / "state.json"
    result = handle_event(build_config(screenshot_dir), state_file=state_file)

    assert result == newest.resolve()
    assert load_history_state(state_file).history == [str(newest.resolve())]
