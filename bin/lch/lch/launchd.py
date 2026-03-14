import os
import plistlib
import subprocess
from dataclasses import dataclass
from pathlib import Path

from lch.jobs import JobDefinition, get_job_definition


@dataclass(frozen=True)
class JobPaths:
    plist_path: Path
    stdout_log_path: Path
    stderr_log_path: Path


def get_home_directory(home: Path | None = None) -> Path:
    if home is not None:
        return home.expanduser()
    return Path(os.environ.get("HOME", str(Path.home()))).expanduser()


def get_job_paths(job: JobDefinition, *, home: Path | None = None) -> JobPaths:
    resolved_home = get_home_directory(home)
    return JobPaths(
        plist_path=resolved_home / "Library/LaunchAgents" / f"{job.label}.plist",
        stdout_log_path=resolved_home / "Library/Logs" / f"{job.label}.out.log",
        stderr_log_path=resolved_home / "Library/Logs" / f"{job.label}.err.log",
    )


def get_lch_executable_path() -> Path:
    return Path(os.environ.get("LCH_BIN_PATH", str(Path.home() / ".local/bin/lch"))).expanduser()


def get_tool_executable_path(tool_name: str) -> Path:
    return Path(os.environ.get(f"{tool_name.upper().replace('-', '_')}_BIN_PATH", str(get_home_directory() / f".local/bin/{tool_name}"))).expanduser()


def resolve_watch_path(job: JobDefinition) -> Path:
    result = subprocess.run(job.watch_path_command, capture_output=True, text=True, check=True)
    return Path(result.stdout.strip()).expanduser().resolve()


def build_launch_agent_plist(
    job: JobDefinition,
    *,
    watch_path: Path,
    executable_path: Path,
    paths: JobPaths,
) -> dict[str, object]:
    return {
        "Label": job.label,
        "ProgramArguments": [str(executable_path), "run", job.job_id],
        "WatchPaths": [str(watch_path)],
        "StandardOutPath": str(paths.stdout_log_path),
        "StandardErrorPath": str(paths.stderr_log_path),
        "RunAtLoad": True,
    }


def install_job(job_id: str) -> Path:
    job = get_job_definition(job_id)
    paths = get_job_paths(job)
    watch_path = resolve_watch_path(job)
    plist_payload = build_launch_agent_plist(
        job,
        watch_path=watch_path,
        executable_path=get_lch_executable_path(),
        paths=paths,
    )

    paths.plist_path.parent.mkdir(parents=True, exist_ok=True)
    paths.stdout_log_path.parent.mkdir(parents=True, exist_ok=True)
    paths.plist_path.write_bytes(plistlib.dumps(plist_payload))

    subprocess.run(["launchctl", "unload", str(paths.plist_path)], capture_output=True, text=True)
    subprocess.run(["launchctl", "load", str(paths.plist_path)], check=True)
    return paths.plist_path


def uninstall_job(job_id: str) -> Path:
    job = get_job_definition(job_id)
    paths = get_job_paths(job)
    if paths.plist_path.exists():
        subprocess.run(["launchctl", "unload", str(paths.plist_path)], capture_output=True, text=True)
        paths.plist_path.unlink()
    return paths.plist_path


def status_job(job_id: str) -> str:
    job = get_job_definition(job_id)
    result = subprocess.run(["launchctl", "list", job.label], capture_output=True, text=True)
    return "loaded" if result.returncode == 0 else "not loaded"


def logs_job(job_id: str) -> tuple[Path, Path]:
    job = get_job_definition(job_id)
    paths = get_job_paths(job)
    return paths.stdout_log_path, paths.stderr_log_path


def run_job(job_id: str) -> None:
    job = get_job_definition(job_id)
    command = list(job.dispatch_command)
    tool_path = get_tool_executable_path(command[0])
    if tool_path.exists():
        command[0] = str(tool_path)
    subprocess.run(command, check=True)
