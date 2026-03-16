import fnmatch
import subprocess
from pathlib import Path

from screenshot.config import ScreenshotConfig
from screenshot.paths import format_user_path
from screenshot.state import load_history_state, write_history_state


def _matches_screenshot_pattern(path: Path, patterns: tuple[str, ...]) -> bool:
    return any(fnmatch.fnmatch(path.name, pattern) for pattern in patterns)


def find_newest_screenshot(config: ScreenshotConfig) -> Path | None:
    if not config.screenshot_dir.exists():
        return None

    candidates = [
        path
        for path in config.screenshot_dir.iterdir()
        if path.is_file() and _matches_screenshot_pattern(path, config.filename_patterns)
    ]
    if not candidates:
        return None

    return max(candidates, key=lambda candidate: (candidate.stat().st_mtime_ns, candidate.name))


def copy_path_to_clipboard(text: str) -> None:
    commands = [
        ["pbcopy"],
        ["wl-copy"],
        ["xclip", "-selection", "clipboard"],
    ]
    for command in commands:
        try:
            subprocess.run(
                command,
                input=text,
                text=True,
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return
        except (FileNotFoundError, OSError, subprocess.CalledProcessError):
            continue


def handle_event(
    config: ScreenshotConfig,
    *,
    state_file: Path | None = None,
    copy_to_clipboard=copy_path_to_clipboard,
) -> Path | None:
    newest = find_newest_screenshot(config)
    if newest is None:
        return None

    newest_path = str(newest.resolve())
    state = load_history_state(state_file)
    if state.history and state.history[0] == newest_path:
        return newest.resolve()

    copy_to_clipboard(format_user_path(newest_path))
    history = [newest_path, *[entry for entry in state.history if entry != newest_path]]
    write_history_state(history[: config.clipboard_history_limit], state_file)
    return newest.resolve()


def list_history(*, state_file: Path | None = None) -> list[str]:
    return load_history_state(state_file).history


def copy_history_entry(
    index: int,
    *,
    state_file: Path | None = None,
    copy_to_clipboard=copy_path_to_clipboard,
) -> str:
    history = load_history_state(state_file).history
    entry_index = index - 1
    if entry_index < 0 or entry_index >= len(history):
        raise IndexError("History index out of range")

    entry = history[entry_index]
    formatted_entry = format_user_path(entry)
    copy_to_clipboard(formatted_entry)
    return formatted_entry
