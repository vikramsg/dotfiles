import shlex
import subprocess
from pathlib import Path

from screenshot.config import load_config


def build_rsync_command(*, config_file: Path | None = None) -> list[str]:
    config = load_config(config_file=config_file)
    return [
        "rsync",
        "-avz",
        "--include=Screenshot *.png",
        "--include=Screen Shot *.png",
        "--exclude=*",
        f"{config.screenshot_dir.resolve()}/",
        f"{config.sync.vm_host}:{config.sync.remote_dir}",
    ]


def format_rsync_command(*, config_file: Path | None = None) -> str:
    return shlex.join(build_rsync_command(config_file=config_file))


def run_sync(*, config_file: Path | None = None) -> None:
    subprocess.run(build_rsync_command(config_file=config_file), check=True, text=True)
