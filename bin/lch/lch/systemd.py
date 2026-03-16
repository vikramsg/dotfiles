import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from lch.jobs import JobDefinition, get_job_definition
from lch.jobs import list_job_definitions


@dataclass(frozen=True)
class JobUnitPaths:
    path_unit: Path
    service_unit: Path


@dataclass(frozen=True)
class KnownJobStatus:
    job_id: str
    label: str
    installed: bool
    loaded: bool


def get_home_directory(home: Path | None = None) -> Path:
    if home is not None:
        return home.expanduser()
    return Path(os.environ.get("HOME", str(Path.home()))).expanduser()


def get_systemd_user_directory() -> Path:
    return get_home_directory() / ".config/systemd/user"


def get_lch_executable_path() -> Path:
    return Path(os.environ.get("LCH_BIN_PATH", str(get_home_directory() / ".local/bin/lch"))).expanduser()


def get_job_unit_paths(job: JobDefinition) -> JobUnitPaths:
    unit_directory = get_systemd_user_directory()
    return JobUnitPaths(
        path_unit=unit_directory / f"{job.label}.path",
        service_unit=unit_directory / f"{job.label}.service",
    )


def resolve_watch_path(job: JobDefinition) -> Path:
    result = subprocess.run(job.watch_path_command, capture_output=True, text=True, check=True)
    return Path(result.stdout.strip()).expanduser().resolve()


def build_path_unit(job: JobDefinition, *, watch_path: Path) -> str:
    return "\n".join(
        [
            "[Unit]",
            f"Description=Watch path for {job.label}",
            "",
            "[Path]",
            f"PathModified={watch_path}",
            f"PathChanged={watch_path}",
            f"Unit={job.label}.service",
            "",
            "[Install]",
            "WantedBy=default.target",
            "",
        ]
    )


def build_service_unit(job: JobDefinition, *, executable_path: Path) -> str:
    return "\n".join(
        [
            "[Unit]",
            f"Description=Dispatch {job.label}",
            "",
            "[Service]",
            "Type=oneshot",
            f"ExecStart={executable_path} run {job.job_id}",
            "",
        ]
    )


def install_job(job_id: str) -> Path:
    if not sys.platform.startswith("linux"):
        raise RuntimeError("systemd jobs can only be installed on Linux")

    job = get_job_definition(job_id)
    paths = get_job_unit_paths(job)
    watch_path = resolve_watch_path(job)
    executable_path = get_lch_executable_path()

    paths.path_unit.parent.mkdir(parents=True, exist_ok=True)
    paths.path_unit.write_text(build_path_unit(job, watch_path=watch_path))
    paths.service_unit.write_text(build_service_unit(job, executable_path=executable_path))

    subprocess.run(["systemctl", "--user", "daemon-reload"], check=True, text=True)
    subprocess.run(["systemctl", "--user", "enable", "--now", f"{job.label}.path"], check=True, text=True)
    return paths.path_unit


def uninstall_job(job_id: str) -> Path:
    job = get_job_definition(job_id)
    paths = get_job_unit_paths(job)

    subprocess.run(
        ["systemctl", "--user", "disable", "--now", f"{job.label}.path"],
        check=False,
        text=True,
        capture_output=True,
    )
    if paths.path_unit.exists():
        paths.path_unit.unlink()
    if paths.service_unit.exists():
        paths.service_unit.unlink()
    subprocess.run(["systemctl", "--user", "daemon-reload"], check=True, text=True)
    return paths.path_unit


def status_job(job_id: str) -> str:
    job = get_job_definition(job_id)
    result = subprocess.run(
        ["systemctl", "--user", "is-active", f"{job.label}.path"],
        check=False,
        text=True,
        capture_output=True,
    )
    return "loaded" if result.returncode == 0 else "not loaded"


def list_known_jobs() -> list[KnownJobStatus]:
    rows: list[KnownJobStatus] = []
    for job in list_job_definitions():
        paths = get_job_unit_paths(job)
        rows.append(
            KnownJobStatus(
                job_id=job.job_id,
                label=job.label,
                installed=paths.path_unit.exists(),
                loaded=status_job(job.job_id) == "loaded",
            )
        )
    return rows


def logs_job(job_id: str) -> tuple[str, str]:
    job = get_job_definition(job_id)
    return (
        f"journalctl --user -u {job.label}.service",
        f"journalctl --user -u {job.label}.path",
    )
