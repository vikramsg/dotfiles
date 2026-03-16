from pathlib import Path

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
    path.touch()
    path.chmod(0o644)
    path_stat = (mtime, mtime)
    import os

    os.utime(path, path_stat)
    return path


def test_on_event_copies_newest_matching_screenshot(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    screenshot_dir = tmp_path / "Screenshots"
    older = write_file(screenshot_dir / "Screenshot 2026-03-14 at 9.00.00 AM.png", mtime=10)
    newer = write_file(screenshot_dir / "Screen Shot 2026-03-14 at 9.01.00 AM.png", mtime=20)
    write_file(screenshot_dir / "notes.txt", mtime=30)

    from screenshot.clipboard import handle_event

    copied: dict[str, str] = {}

    def fake_pbcopy(text: str) -> None:
        copied["value"] = text

    result = handle_event(
        build_config(screenshot_dir),
        state_file=tmp_path / "state.json",
        copy_to_clipboard=fake_pbcopy,
    )

    assert older.exists()
    assert result == newer.resolve()
    assert copied["value"] == r"~/Screenshots/Screen\ Shot\ 2026-03-14\ at\ 9.01.00\ AM.png"


def test_on_event_ignores_non_screenshot_filenames(tmp_path):
    screenshot_dir = tmp_path / "Screenshots"
    write_file(screenshot_dir / "IMG_1001.PNG", mtime=10)
    write_file(screenshot_dir / "notes.txt", mtime=20)

    from screenshot.clipboard import handle_event

    copied: list[str] = []
    result = handle_event(
        build_config(screenshot_dir),
        state_file=tmp_path / "state.json",
        copy_to_clipboard=copied.append,
    )

    assert result is None
    assert copied == []


def test_on_event_skips_copy_when_history_head_matches_newest(tmp_path):
    screenshot_dir = tmp_path / "Screenshots"
    newest = write_file(screenshot_dir / "Screenshot 2026-03-14 at 9.01.00 AM.png", mtime=20)
    state_file = tmp_path / "state.json"
    state_file.write_text('{"history": ["' + str(newest.resolve()) + '"]}')

    from screenshot.clipboard import handle_event

    copied: list[str] = []
    result = handle_event(
        build_config(screenshot_dir),
        state_file=state_file,
        copy_to_clipboard=copied.append,
    )

    assert result == newest.resolve()
    assert copied == []


def test_find_newest_screenshot_uses_nanosecond_mtime_for_close_writes(tmp_path, monkeypatch):
    from types import SimpleNamespace

    screenshot_dir = tmp_path / "Screenshots"
    first = write_file(screenshot_dir / "Screen Shot 2026-03-14 at 10.07.00 AM.png", mtime=20)
    second = write_file(screenshot_dir / "Screen Shot 2026-03-14 at 10.08.00 AM.png", mtime=20)

    from screenshot.clipboard import find_newest_screenshot

    original_stat = Path.stat

    def fake_stat(path: Path, *args, **kwargs):
        if path == first:
            return SimpleNamespace(st_mtime=20.0, st_mtime_ns=20_000_000_001)
        if path == second:
            return SimpleNamespace(st_mtime=20.0, st_mtime_ns=20_000_000_999)
        return original_stat(path, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", fake_stat)

    result = find_newest_screenshot(build_config(screenshot_dir))

    assert result == second
