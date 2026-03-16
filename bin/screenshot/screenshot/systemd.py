import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from screenshot.config import load_config


UNIT_BASENAME = "screenshot-clipboard"


@dataclass(frozen=True)
class SystemdUnitPaths:
    service_path: Path
    path_path: Path


def get_home_directory() -> Path:
    return Path(os.environ.get("HOME", str(Path.home()))).expanduser()


def get_systemd_user_directory() -> Path:
    return get_home_directory() / ".config/systemd/user"


def get_screenshot_executable_path() -> Path:
    return Path(os.environ.get("SCREENSHOT_BIN_PATH", str(get_home_directory() / ".local/bin/screenshot"))).expanduser()


def get_unit_paths() -> SystemdUnitPaths:
    systemd_user_directory = get_systemd_user_directory()
    return SystemdUnitPaths(
        service_path=systemd_user_directory / f"{UNIT_BASENAME}.service",
        path_path=systemd_user_directory / f"{UNIT_BASENAME}.path",
    )


def render_service_unit(*, executable_path: Path) -> str:
    return "\n".join(
        [
            "[Unit]",
            "Description=Update screenshot clipboard history on directory changes",
            "",
            "[Service]",
            "Type=oneshot",
            f"ExecStart={executable_path} clipboard on-event",
            "",
        ]
    )


def render_path_unit(*, watch_path: Path) -> str:
    return "\n".join(
        [
            "[Unit]",
            "Description=Watch screenshot directory for updates",
            "",
            "[Path]",
            f"PathModified={watch_path}",
            f"PathChanged={watch_path}",
            f"Unit={UNIT_BASENAME}.service",
            "",
            "[Install]",
            "WantedBy=default.target",
            "",
        ]
    )


def write_systemd_units(*, watch_path: Path, executable_path: Path) -> SystemdUnitPaths:
    unit_paths = get_unit_paths()
    unit_paths.service_path.parent.mkdir(parents=True, exist_ok=True)
    unit_paths.service_path.write_text(render_service_unit(executable_path=executable_path))
    unit_paths.path_path.write_text(render_path_unit(watch_path=watch_path))
    return unit_paths


def apply_linux_screenshot_watcher(*, config_file: Path | None = None) -> Path:
    if not sys.platform.startswith("linux"):
        raise RuntimeError("Linux systemd user units can only be applied on Linux")

    watch_path = load_config(config_file=config_file).screenshot_dir.expanduser().resolve()
    watch_path.mkdir(parents=True, exist_ok=True)
    executable_path = get_screenshot_executable_path()
    write_systemd_units(watch_path=watch_path, executable_path=executable_path)

    subprocess.run(["systemctl", "--user", "daemon-reload"], check=True, text=True)
    subprocess.run(["systemctl", "--user", "enable", "--now", f"{UNIT_BASENAME}.path"], check=True, text=True)
    subprocess.run(["systemctl", "--user", "start", f"{UNIT_BASENAME}.service"], check=True, text=True)
    return watch_path
