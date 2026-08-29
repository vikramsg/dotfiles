import os
import shlex
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from lch.config import load_config
from lch.jobs import JobDefinition, JobIdentity, get_job_definition, get_job_identity
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


def get_job_unit_paths(job: JobDefinition | JobIdentity) -> JobUnitPaths:
    unit_directory = get_systemd_user_directory()
    return JobUnitPaths(
        path_unit=unit_directory / f"{job.label}.path",
        service_unit=unit_directory / f"{job.label}.service",
    )


def resolve_watch_path(job: JobDefinition) -> Path:
    result = subprocess.run(job.watch_path_command, capture_output=True, text=True, check=True)
    return Path(result.stdout.strip()).expanduser().resolve()


def build_path_unit(job: JobDefinition | JobIdentity, *, watch_path: Path) -> str:
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


def build_watcher_service_unit(job: JobIdentity, *, dispatch_command: list[str]) -> str:
    return "\n".join(
        [
            "[Unit]",
            f"Description=Dispatch {job.label}",
            "",
            "[Service]",
            "Type=oneshot",
            f"ExecStart={shlex.join(dispatch_command)}",
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


def install_watcher(
    job_id: str, *, watch_path: Path, dispatch_command: list[str]
) -> Path:
    if not sys.platform.startswith("linux"):
        raise RuntimeError("systemd jobs can only be installed on Linux")

    job = get_job_identity(job_id)
    paths = get_job_unit_paths(job)
    paths.path_unit.parent.mkdir(parents=True, exist_ok=True)
    paths.path_unit.write_text(
        build_path_unit(job, watch_path=watch_path.expanduser().resolve())
    )
    paths.service_unit.write_text(
        build_watcher_service_unit(job, dispatch_command=dispatch_command)
    )
    subprocess.run(["systemctl", "--user", "daemon-reload"], check=True, text=True)
    subprocess.run(
        ["systemctl", "--user", "enable", "--now", f"{job.label}.path"],
        check=True,
        text=True,
    )
    return paths.path_unit


def uninstall_job(job_id: str) -> Path:
    job = get_job_identity(job_id)
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
    job = get_job_identity(job_id)
    return "loaded" if is_job_loaded(job.label) else "not loaded"


def is_job_loaded(label: str) -> bool:
    result = subprocess.run(
        ["systemctl", "--user", "is-active", f"{label}.path"],
        check=False,
        text=True,
        capture_output=True,
    )
    return result.returncode == 0


def list_known_jobs() -> list[KnownJobStatus]:
    rows: dict[str, KnownJobStatus] = {}
    for job in list_job_definitions():
        paths = get_job_unit_paths(job)
        rows[job.job_id] = KnownJobStatus(
            job_id=job.job_id,
            label=job.label,
            installed=paths.path_unit.exists(),
            loaded=is_job_loaded(job.label),
        )

    namespace_prefix = f"{load_config().namespace}."
    unit_directory = get_systemd_user_directory()
    for path_unit in sorted(unit_directory.glob(f"{namespace_prefix}*.path")):
        label = path_unit.name.removesuffix(".path")
        job_id = label.removeprefix(namespace_prefix)
        rows.setdefault(
            job_id,
            KnownJobStatus(
                job_id=job_id,
                label=label,
                installed=True,
                loaded=is_job_loaded(label),
            ),
        )
    return [rows[job_id] for job_id in sorted(rows)]


def logs_job(job_id: str) -> tuple[str, str]:
    job = get_job_identity(job_id)
    return (
        f"journalctl --user -u {job.label}.service",
        f"journalctl --user -u {job.label}.path",
    )
