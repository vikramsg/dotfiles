import os
import plistlib
import re
import signal
import subprocess
import sys
import time
from xml.parsers.expat import ExpatError
from dataclasses import dataclass
from functools import singledispatch
from math import ceil
from pathlib import Path

from lch.config import (
    ApplicationDefinition,
    ApplicationService,
    CommandService,
    LinuxApplication,
    MacOSApplication,
    Service,
    load_config,
)
from lch.jobs import (
    JobDefinition,
    JobIdentity,
    ServiceDefinition,
    get_job_identity,
    get_launchd_job_definition,
    list_launchd_job_definitions,
)


SERVICE_RESTART_THROTTLE_SECONDS = 10
LAUNCHD_PATH = f"{Path.home() / '.local/bin'}:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"


@dataclass(frozen=True)
class JobPaths:
    plist_path: Path
    stdout_log_path: Path
    stderr_log_path: Path


@dataclass(frozen=True)
class KnownJobStatus:
    job_id: str
    label: str
    installed: bool
    loaded: bool


@dataclass(frozen=True)
class DiscoveredLaunchdJob:
    label: str
    kind: str
    loaded: bool
    source: str
    plist_path: Path


@dataclass(frozen=True)
class PaginatedLaunchdJobs:
    page: int
    page_size: int
    total_items: int
    total_pages: int
    items: list[DiscoveredLaunchdJob]


def format_display_path(path: Path) -> str:
    home_directory = get_home_directory().resolve()
    resolved_path = path.expanduser().resolve()
    try:
        relative_path = resolved_path.relative_to(home_directory)
    except ValueError:
        return str(resolved_path)
    return f"~/{relative_path.as_posix()}" if relative_path != Path(".") else "~"


def get_home_directory(home: Path | None = None) -> Path:
    if home is not None:
        return home.expanduser()
    return Path(os.environ.get("HOME", str(Path.home()))).expanduser()


def get_job_paths(
    job: JobDefinition | JobIdentity | ServiceDefinition, *, home: Path | None = None
) -> JobPaths:
    resolved_home = get_home_directory(home)
    return JobPaths(
        plist_path=resolved_home / "Library/LaunchAgents" / f"{job.label}.plist",
        stdout_log_path=resolved_home / "Library/Logs" / f"{job.label}.out.log",
        stderr_log_path=resolved_home / "Library/Logs" / f"{job.label}.err.log",
    )


def get_launchagents_directory() -> Path:
    return get_home_directory() / "Library/LaunchAgents"


def get_logs_directory() -> Path:
    return get_home_directory() / "Library/Logs"


def get_lch_executable_path() -> Path:
    return Path(os.environ.get("LCH_BIN_PATH", str(Path.home() / ".local/bin/lch"))).expanduser()


def get_tool_executable_path(tool_name: str) -> Path:
    return Path(os.environ.get(f"{tool_name.upper().replace('-', '_')}_BIN_PATH", str(get_home_directory() / f".local/bin/{tool_name}"))).expanduser()


def get_standard_launchd_roots() -> list[Path]:
    home_directory = get_home_directory()
    return [
        home_directory / "Library/LaunchAgents",
        Path("/Library/LaunchAgents"),
        Path("/System/Library/LaunchAgents"),
        Path("/Library/LaunchDaemons"),
        Path("/System/Library/LaunchDaemons"),
    ]


def _format_source_directory(path: Path) -> str:
    home_directory = get_home_directory()
    try:
        relative_path = path.resolve().relative_to(home_directory)
    except ValueError:
        return str(path)
    return f"~/{relative_path.as_posix()}"


def _launchd_kind_for_root(path: Path) -> str:
    return "daemon" if "LaunchDaemons" in path.parts else "agent"


def discover_launchd_jobs(*, search_roots: list[Path] | None = None) -> list[DiscoveredLaunchdJob]:
    jobs: list[DiscoveredLaunchdJob] = []
    for root in search_roots or get_standard_launchd_roots():
        if not root.exists():
            continue
        for plist_path in sorted(root.glob("*.plist")):
            try:
                payload = plistlib.loads(plist_path.read_bytes())
            except (OSError, ExpatError, plistlib.InvalidFileException):
                continue
            label = payload.get("Label")
            if not isinstance(label, str) or not label:
                continue
            jobs.append(
                DiscoveredLaunchdJob(
                    label=label,
                    kind=_launchd_kind_for_root(root),
                    loaded=is_job_loaded(label),
                    source=_format_source_directory(root),
                    plist_path=plist_path,
                )
            )
    return sorted(jobs, key=lambda job: (job.label, str(job.plist_path)))


def paginate_launchd_jobs(
    jobs: list[DiscoveredLaunchdJob],
    *,
    page: int,
    page_size: int,
) -> PaginatedLaunchdJobs:
    if page < 1:
        raise ValueError("page must be >= 1")
    if page_size < 1:
        raise ValueError("page_size must be >= 1")

    total_items = len(jobs)
    total_pages = max(1, ceil(total_items / page_size))
    start = (page - 1) * page_size
    end = start + page_size
    return PaginatedLaunchdJobs(
        page=page,
        page_size=page_size,
        total_items=total_items,
        total_pages=total_pages,
        items=jobs[start:end],
    )


def render_launchd_job_page(*, page: int = 1, page_size: int = 25) -> str:
    paginated = paginate_launchd_jobs(discover_launchd_jobs(), page=page, page_size=page_size)
    lines = [f"PAGE {paginated.page}/{paginated.total_pages}  TOTAL {paginated.total_items}  PAGE_SIZE {paginated.page_size}", "", "LABEL  TYPE  LOADED  SOURCE"]
    for job in paginated.items:
        loaded = "yes" if job.loaded else "no"
        lines.append(f"{job.label}  {job.kind}  {loaded}  {job.source}")
    return "\n".join(lines)


def render_full_launchd_job_list() -> str:
    jobs = discover_launchd_jobs()
    lines = [f"TOTAL {len(jobs)}", "", "LABEL  TYPE  LOADED  SOURCE"]
    for job in jobs:
        loaded = "yes" if job.loaded else "no"
        lines.append(f"{job.label}  {job.kind}  {loaded}  {job.source}")
    return "\n".join(lines)


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


def build_launch_agent_service_plist(
    service: ServiceDefinition,
    *,
    executable_path: Path,
    paths: JobPaths,
) -> dict[str, object]:
    return {
        "Label": service.label,
        "ProgramArguments": [str(executable_path), "run", service.job_id],
        "StandardOutPath": str(paths.stdout_log_path),
        "StandardErrorPath": str(paths.stderr_log_path),
        "EnvironmentVariables": {"PATH": LAUNCHD_PATH},
        "RunAtLoad": True,
        "KeepAlive": True,
        "ThrottleInterval": SERVICE_RESTART_THROTTLE_SECONDS,
    }


def build_watcher_plist(
    job: JobIdentity,
    *,
    watch_path: Path,
    dispatch_command: list[str],
    paths: JobPaths,
) -> dict[str, object]:
    return {
        "Label": job.label,
        "ProgramArguments": dispatch_command,
        "WatchPaths": [str(watch_path)],
        "StandardOutPath": str(paths.stdout_log_path),
        "StandardErrorPath": str(paths.stderr_log_path),
        "RunAtLoad": True,
    }


@singledispatch
def build_install_payload(
    job: JobDefinition | ServiceDefinition,
    *,
    paths: JobPaths,
) -> dict[str, object]:
    raise TypeError(f"Unsupported job definition: {type(job).__name__}")


@build_install_payload.register
def _(job: JobDefinition, *, paths: JobPaths) -> dict[str, object]:
    return build_launch_agent_plist(
        job,
        watch_path=resolve_watch_path(job),
        executable_path=get_lch_executable_path(),
        paths=paths,
    )


@build_install_payload.register
def _(job: ServiceDefinition, *, paths: JobPaths) -> dict[str, object]:
    return build_launch_agent_service_plist(
        job,
        executable_path=get_lch_executable_path(),
        paths=paths,
    )


def write_and_load_plist(paths: JobPaths, plist_payload: dict[str, object]) -> Path:
    paths.plist_path.parent.mkdir(parents=True, exist_ok=True)
    paths.stdout_log_path.parent.mkdir(parents=True, exist_ok=True)
    paths.plist_path.write_bytes(plistlib.dumps(plist_payload))

    subprocess.run(
        ["launchctl", "unload", str(paths.plist_path)], capture_output=True, text=True
    )
    subprocess.run(["launchctl", "load", str(paths.plist_path)], check=True)
    return paths.plist_path


def install_job(job_id: str) -> Path:
    job = get_launchd_job_definition(job_id)
    paths = get_job_paths(job)
    return write_and_load_plist(paths, build_install_payload(job, paths=paths))


def install_watcher(
    job_id: str, *, watch_path: Path, dispatch_command: list[str]
) -> Path:
    job = get_job_identity(job_id)
    paths = get_job_paths(job)
    plist_payload = build_watcher_plist(
        job,
        watch_path=watch_path.expanduser().resolve(),
        dispatch_command=dispatch_command,
        paths=paths,
    )
    return write_and_load_plist(paths, plist_payload)


def uninstall_job(job_id: str) -> Path:
    job = get_job_identity(job_id)
    paths = get_job_paths(job)
    if paths.plist_path.exists():
        subprocess.run(["launchctl", "unload", str(paths.plist_path)], capture_output=True, text=True)
        paths.plist_path.unlink()
    return paths.plist_path


def status_job(job_id: str) -> str:
    job = get_job_identity(job_id)
    result = subprocess.run(["launchctl", "list", job.label], capture_output=True, text=True)
    return "loaded" if result.returncode == 0 else "not loaded"


def is_job_loaded(label: str) -> bool:
    result = subprocess.run(["launchctl", "list", label], capture_output=True, text=True)
    return result.returncode == 0


def list_known_jobs() -> list[KnownJobStatus]:
    rows: dict[str, KnownJobStatus] = {}
    for job in list_launchd_job_definitions():
        paths = get_job_paths(job)
        rows[job.job_id] = KnownJobStatus(
            job_id=job.job_id,
            label=job.label,
            installed=paths.plist_path.exists(),
            loaded=is_job_loaded(job.label),
        )

    namespace_prefix = f"{load_config().namespace}."
    discovered_jobs = discover_launchd_jobs(
        search_roots=[get_launchagents_directory()]
    )
    for job in discovered_jobs:
        if not job.label.startswith(namespace_prefix):
            continue
        job_id = job.label.removeprefix(namespace_prefix)
        rows.setdefault(
            job_id,
            KnownJobStatus(
                job_id=job_id,
                label=job.label,
                installed=True,
                loaded=job.loaded,
            ),
        )
    return [rows[job_id] for job_id in sorted(rows)]


def logs_job(job_id: str) -> tuple[Path, Path]:
    job = get_job_identity(job_id)
    paths = get_job_paths(job)
    return paths.stdout_log_path, paths.stderr_log_path


def resolve_application_executable(application_path: Path) -> Path:
    info_path = application_path / "Contents/Info.plist"
    if not application_path.is_dir() or not info_path.is_file():
        raise RuntimeError(f"Invalid macOS application bundle: {application_path}")
    try:
        info = plistlib.loads(info_path.read_bytes())
    except (OSError, plistlib.InvalidFileException) as exc:
        raise RuntimeError(f"Invalid macOS application Info.plist: {info_path}") from exc
    executable = info.get("CFBundleExecutable")
    if not isinstance(executable, str) or not executable:
        raise RuntimeError(f"Missing CFBundleExecutable in {info_path}")
    executable_path = application_path / "Contents/MacOS" / executable
    if not executable_path.is_file():
        raise RuntimeError(f"Missing macOS application executable: {executable_path}")
    return executable_path


def application_pids(executable_path: Path) -> set[int]:
    pattern = rf"(^| ){re.escape(str(executable_path))}( |$)"
    result = subprocess.run(
        ["/usr/bin/pgrep", "-U", str(os.getuid()), "-f", pattern],
        capture_output=True,
        text=True,
        check=False,
    )
    return {
        int(raw_pid)
        for raw_pid in result.stdout.splitlines()
        if raw_pid.isdigit()
    }


def stop_application(executable_path: Path, *, timeout: float = 5) -> None:
    pids = application_pids(executable_path)
    if not pids:
        return
    for pid in pids:
        try:
            os.kill(pid, signal.SIGTERM)
        except (PermissionError, ProcessLookupError):
            continue

    deadline = time.monotonic() + timeout
    while application_pids(executable_path):
        if time.monotonic() >= deadline:
            raise RuntimeError(f"Application did not stop: {executable_path}")
        time.sleep(0.1)


def run_macos_application(application_path: Path, *, paths: JobPaths) -> None:
    if sys.platform != "darwin":
        raise RuntimeError("macOS application services can only run on macOS")
    executable_path = resolve_application_executable(application_path)
    stop_application(executable_path)
    paths.stdout_log_path.parent.mkdir(parents=True, exist_ok=True)
    paths.stdout_log_path.touch(exist_ok=True)
    paths.stderr_log_path.touch(exist_ok=True)
    stopping = False

    def request_stop(_signum: int, _frame: object) -> None:
        nonlocal stopping
        stopping = True

    previous_term = signal.signal(signal.SIGTERM, request_stop)
    previous_interrupt = signal.signal(signal.SIGINT, request_stop)
    try:
        process = subprocess.Popen(
            [
                "/usr/bin/open",
                "-W",
                "-g",
                "--stdout",
                str(paths.stdout_log_path),
                "--stderr",
                str(paths.stderr_log_path),
                str(application_path),
            ]
        )
        while process.poll() is None and not stopping:
            time.sleep(0.1)
        if stopping:
            stop_application(executable_path)
            if process.poll() is None:
                process.terminate()
        return_code = process.wait()
        if return_code != 0 and not stopping:
            raise subprocess.CalledProcessError(return_code, process.args)
    finally:
        signal.signal(signal.SIGTERM, previous_term)
        signal.signal(signal.SIGINT, previous_interrupt)


@singledispatch
def run_application(application: ApplicationDefinition, *, paths: JobPaths) -> None:
    raise TypeError(f"Unsupported application definition: {type(application).__name__}")


@run_application.register
def _(application: MacOSApplication, *, paths: JobPaths) -> None:
    run_macos_application(application.path, paths=paths)


@run_application.register
def _(application: LinuxApplication, *, paths: JobPaths) -> None:
    raise RuntimeError("Linux application services are not implemented")


@singledispatch
def run_service(service: Service, *, paths: JobPaths) -> None:
    raise TypeError(f"Unsupported service definition: {type(service).__name__}")


@run_service.register
def _(service: CommandService, *, paths: JobPaths) -> None:
    command = list(service.command)
    tool_path = get_tool_executable_path(command[0])
    if tool_path.exists():
        command[0] = str(tool_path)
    os.execvp(command[0], command)


@run_service.register
def _(service: ApplicationService, *, paths: JobPaths) -> None:
    run_application(service.application, paths=paths)


@singledispatch
def run_definition(
    job: JobDefinition | ServiceDefinition,
    *,
    paths: JobPaths,
) -> None:
    raise TypeError(f"Unsupported job definition: {type(job).__name__}")


@run_definition.register
def _(job: JobDefinition, *, paths: JobPaths) -> None:
    command = list(job.dispatch_command)
    tool_path = get_tool_executable_path(command[0])
    if tool_path.exists():
        command[0] = str(tool_path)
    subprocess.run(command, check=True)


@run_definition.register
def _(job: ServiceDefinition, *, paths: JobPaths) -> None:
    run_service(job.service, paths=paths)


def run_job(job_id: str) -> None:
    job = get_launchd_job_definition(job_id)
    run_definition(job, paths=get_job_paths(job))
