import subprocess
import sys
from pathlib import Path

from screenshot.config import load_config


def is_macos() -> bool:
    return sys.platform == "darwin"


def apply_macos_screenshot_location(*, config_file: Path | None = None) -> Path:
    if not is_macos():
        raise RuntimeError("macOS screenshot settings can only be applied on macOS")

    screenshot_dir = load_config(config_file=config_file).screenshot_dir.expanduser().resolve()
    screenshot_dir.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["defaults", "write", "com.apple.screencapture", "location", str(screenshot_dir)],
        check=True,
        text=True,
    )
    subprocess.run(["killall", "SystemUIServer"], check=True, text=True)
    return screenshot_dir
