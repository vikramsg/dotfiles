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


def write_file(path: Path, *, mtime: int) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(path.name)
    import os

    os.utime(path, (mtime, mtime))
    return path


def test_handle_event_prepends_newest_and_trims_to_limit(tmp_path):
    screenshot_dir = tmp_path / "Screenshots"
    state_file = tmp_path / "history.json"

    from screenshot.clipboard import handle_event
    from screenshot.state import load_history_state

    config = build_config(screenshot_dir)
    created: list[Path] = []
    for idx in range(6):
        created.append(
            write_file(
                screenshot_dir / f"Screenshot 2026-03-14 at 9.0{idx}.00 AM.png",
                mtime=idx + 1,
            )
        )
        handle_event(config, state_file=state_file, copy_to_clipboard=lambda _text: None)

    history = load_history_state(state_file).history

    assert history == [str(path.resolve()) for path in reversed(created[-5:])]


def test_clipboard_list_shows_newest_first_history(tmp_path, monkeypatch):
    state_file = tmp_path / "history.json"
    history = [
        "/tmp/shot-3.png",
        "/tmp/shot-2.png",
        "/tmp/shot-1.png",
    ]
    state_file.write_text('{"history": ["/tmp/shot-3.png", "/tmp/shot-2.png", "/tmp/shot-1.png"]}')
    monkeypatch.setenv("SCREENSHOT_STATE_FILE", str(state_file))

    from screenshot.cli import main

    runner = CliRunner()
    result = runner.invoke(main, ["clipboard", "list"])

    assert result.exit_code == 0
    assert result.output.splitlines() == history


def test_clipboard_copy_by_index_recopies_prior_item(tmp_path, monkeypatch):
    state_file = tmp_path / "history.json"
    state_file.write_text('{"history": ["/tmp/shot-3.png", "/tmp/shot-2.png", "/tmp/shot-1.png"]}')
    monkeypatch.setenv("SCREENSHOT_STATE_FILE", str(state_file))

    copied: list[str] = []

    import screenshot.cli as cli_module

    monkeypatch.setattr(cli_module, "copy_path_to_clipboard", copied.append)

    runner = CliRunner()
    result = runner.invoke(cli_module.main, ["clipboard", "copy", "--index", "2"])

    assert result.exit_code == 0
    assert copied == ["/tmp/shot-2.png"]


def test_clipboard_copy_rejects_out_of_range_index(tmp_path, monkeypatch):
    state_file = tmp_path / "history.json"
    state_file.write_text('{"history": ["/tmp/shot-1.png"]}')
    monkeypatch.setenv("SCREENSHOT_STATE_FILE", str(state_file))

    from screenshot.cli import main

    runner = CliRunner()
    result = runner.invoke(main, ["clipboard", "copy", "--index", "2"])

    assert result.exit_code != 0
    assert "History index out of range" in result.output
