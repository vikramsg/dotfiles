import json
import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ClipboardHistoryState:
    history: list[str]


def get_default_state_file() -> Path:
    return Path("~/.local/state/screenshot/clipboard-history.json").expanduser()


def get_state_file(state_file: Path | None = None) -> Path:
    if state_file is not None:
        return state_file.expanduser()
    return Path(os.environ.get("SCREENSHOT_STATE_FILE", str(get_default_state_file()))).expanduser()


def load_history_state(state_file: Path | None = None) -> ClipboardHistoryState:
    resolved_state_file = get_state_file(state_file)
    if not resolved_state_file.exists():
        return ClipboardHistoryState(history=[])

    payload = json.loads(resolved_state_file.read_text())
    history = payload.get("history", [])
    return ClipboardHistoryState(history=[str(entry) for entry in history])


def write_history_state(history: list[str], state_file: Path | None = None) -> ClipboardHistoryState:
    resolved_state_file = get_state_file(state_file)
    resolved_state_file.parent.mkdir(parents=True, exist_ok=True)
    resolved_state_file.write_text(json.dumps({"history": history}, indent=2))
    return ClipboardHistoryState(history=history)
