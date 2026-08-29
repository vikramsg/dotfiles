import shlex
import subprocess
from pathlib import Path

from screenshot.config import load_config


def get_sync_source(source_id: str, *, config_file: Path | None = None):
    config = load_config(config_file=config_file)
    for source in config.sync.sources:
        if source.id == source_id:
            return source
    raise ValueError(f"unknown screenshot sync source: {source_id}")


def build_rsync_command(
    source_id: str = "system", *, config_file: Path | None = None
) -> list[str]:
    source = get_sync_source(source_id, config_file=config_file)
    return [
        "rsync",
        "-avz",
        *(f"--exclude={pattern}" for pattern in source.exclude),
        *(f"--include={pattern}" for pattern in source.include),
        "--exclude=*",
        f"{source.local_dir.resolve()}/",
        f"{source.vm_host}:{source.remote_dir}",
    ]


def format_rsync_command(source_id: str = "system", *, config_file: Path | None = None) -> str:
    return shlex.join(build_rsync_command(source_id, config_file=config_file))


def run_sync(source_id: str = "system", *, config_file: Path | None = None) -> None:
    source = get_sync_source(source_id, config_file=config_file)
    subprocess.run(["ssh", source.vm_host, "mkdir", "-p", source.remote_dir], check=True, text=True)
    subprocess.run(build_rsync_command(source_id, config_file=config_file), check=True, text=True)
