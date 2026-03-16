import json
import os
from dataclasses import dataclass
from pathlib import Path


DEFAULT_CLIPBOARD_HISTORY_LIMIT = 5
DEFAULT_FILENAME_PATTERNS = (
    "Screenshot *.png",
    "Screen Shot *.png",
)
DEFAULT_SCREENSHOT_DIR = "~/Desktop/Screenshots"


@dataclass(frozen=True)
class SyncConfig:
    vm_host: str
    remote_dir: str


@dataclass(frozen=True)
class ScreenshotConfig:
    screenshot_dir: Path
    clipboard_history_limit: int
    filename_patterns: tuple[str, ...]
    sync: SyncConfig


def _expand_path(raw_path: str | Path) -> Path:
    return Path(raw_path).expanduser()


def get_default_screenshot_dir() -> Path:
    return _expand_path(DEFAULT_SCREENSHOT_DIR)


def get_default_config_file() -> Path:
    return _expand_path("~/.config/screenshot/config.json")


def get_config_file(config_file: Path | None = None) -> Path:
    if config_file is not None:
        return _expand_path(config_file)
    return _expand_path(os.environ.get("SCREENSHOT_CONFIG_FILE", get_default_config_file()))


def load_config(config_file: Path | None = None) -> ScreenshotConfig:
    resolved_config_file = get_config_file(config_file)
    data = json.loads(resolved_config_file.read_text()) if resolved_config_file.exists() else {}
    sync_data = data.get("sync", {})
    configured_dir = os.environ.get("SCREENSHOT_DIR") or data.get("screenshot_dir") or str(get_default_screenshot_dir())
    return ScreenshotConfig(
        screenshot_dir=_expand_path(configured_dir),
        clipboard_history_limit=int(data.get("clipboard_history_limit", DEFAULT_CLIPBOARD_HISTORY_LIMIT)),
        filename_patterns=tuple(data.get("filename_patterns", DEFAULT_FILENAME_PATTERNS)),
        sync=SyncConfig(
            vm_host=sync_data.get("vm_host", ""),
            remote_dir=sync_data.get("remote_dir", ""),
        ),
    )
