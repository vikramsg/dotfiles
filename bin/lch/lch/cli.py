import subprocess
import sys
from pathlib import Path

import click

from lch.config import get_config_file, load_config
from lch.launchd import (
    discover_launchd_jobs,
    format_display_path,
    get_launchagents_directory,
    get_lch_executable_path,
    get_logs_directory,
    get_standard_launchd_roots,
    paginate_launchd_jobs,
    run_job,
)
from lch.launchd import (
    install_job as install_job_launchd,
)
from lch.launchd import install_watcher as install_watcher_launchd
from lch.launchd import (
    list_known_jobs as list_known_jobs_launchd,
)
from lch.launchd import (
    logs_job as logs_job_launchd,
)
from lch.launchd import (
    render_full_launchd_job_list as render_full_launchd_job_list_from_launchd,
)
from lch.launchd import (
    status_job as status_job_launchd,
)
from lch.launchd import (
    uninstall_job as uninstall_job_launchd,
)
from lch.systemd import install_job as install_job_systemd
from lch.systemd import install_watcher as install_watcher_systemd
from lch.systemd import list_known_jobs as list_known_jobs_systemd
from lch.systemd import logs_job as logs_job_systemd
from lch.systemd import status_job as status_job_systemd
from lch.systemd import uninstall_job as uninstall_job_systemd

DEFAULT_LOG_LINES = 20


@click.group()
def main() -> None:
    """Thin launchd orchestrator."""


@main.command("list")
def list_command() -> None:
    """List known lch jobs and their local status."""
    click.echo("JOB  INSTALLED  LOADED  LABEL")
    jobs = (
        list_known_jobs_systemd()
        if sys.platform.startswith("linux")
        else list_known_jobs_launchd()
    )
    for job in jobs:
        installed = "yes" if job.installed else "no"
        loaded = "yes" if job.loaded else "no"
        click.echo(f"{job.job_id}  {installed}  {loaded}  {job.label}")


def render_lch_config() -> str:
    config_file = get_config_file()
    config = load_config()
    lines = [
        f"CONFIG_FILE  {config_file}",
        f"NAMESPACE  {config.namespace}",
        f"LCH_BIN  {format_display_path(get_lch_executable_path())}",
        f"LAUNCHAGENTS_DIR  {format_display_path(get_launchagents_directory())}",
        f"LOGS_DIR  {format_display_path(get_logs_directory())}",
        "",
        "DISCOVERY_ROOTS",
    ]
    lines.extend(format_display_path(path) for path in get_standard_launchd_roots())
    lines.extend(
        [
            "",
            "FORMAT",
            'namespace = "com.vikramsg.dotfiles"',
            "",
            "[services.example]",
            'command = ["example", "run"]',
        ]
    )
    return "\n".join(lines)


@main.command("config")
def config_command() -> None:
    """Show the effective lch configuration model and paths."""
    click.echo(render_lch_config())


def stdout_supports_pager() -> bool:
    return sys.stdout.isatty()


def render_launchd_job_page(*, page: int = 1, page_size: int = 25) -> str:
    paginated = paginate_launchd_jobs(
        discover_launchd_jobs(), page=page, page_size=page_size
    )
    lines = [
        f"PAGE {paginated.page}/{paginated.total_pages}  TOTAL {paginated.total_items}  PAGE_SIZE {paginated.page_size}",
        "",
        "LABEL  TYPE  LOADED  SOURCE",
    ]
    for job in paginated.items:
        loaded = "yes" if job.loaded else "no"
        lines.append(f"{job.label}  {job.kind}  {loaded}  {job.source}")
    return "\n".join(lines)


def render_full_launchd_job_list() -> str:
    return render_full_launchd_job_list_from_launchd()


@main.group("launchd")
def launchd_group() -> None:
    """Browse machine-wide launchd jobs."""


@launchd_group.command("list")
def launchd_list_command() -> None:
    """List launchd jobs with an interactive pager when possible."""
    output = render_full_launchd_job_list()
    if stdout_supports_pager():
        click.echo_via_pager(output)
        return
    click.echo(output)


@launchd_group.command("page")
@click.option("--page", type=int, default=1, show_default=True)
@click.option("--page-size", type=int, default=25, show_default=True)
def launchd_page_command(page: int, page_size: int) -> None:
    """Render one page of discovered launchd jobs."""
    click.echo(render_launchd_job_page(page=page, page_size=page_size))


@main.command("install")
@click.argument("job_id")
def install_command(job_id: str) -> None:
    """Install a launchd job."""
    if sys.platform.startswith("linux"):
        click.echo(str(install_job_systemd(job_id)))
        return
    click.echo(str(install_job_launchd(job_id)))


@main.command("install-watcher")
@click.argument("job_id")
@click.argument("watch_path", type=click.Path(path_type=Path))
@click.argument("dispatch_command", nargs=-1, required=True)
def install_watcher_command(
    job_id: str, watch_path: Path, dispatch_command: tuple[str, ...]
) -> None:
    """Install a watcher with an explicit path and dispatch command."""
    install_watcher = (
        install_watcher_systemd
        if sys.platform.startswith("linux")
        else install_watcher_launchd
    )
    click.echo(
        str(
            install_watcher(
                job_id,
                watch_path=watch_path,
                dispatch_command=list(dispatch_command),
            )
        )
    )


@main.command("uninstall")
@click.argument("job_id")
def uninstall_command(job_id: str) -> None:
    """Uninstall a launchd job."""
    if sys.platform.startswith("linux"):
        click.echo(str(uninstall_job_systemd(job_id)))
        return
    click.echo(str(uninstall_job_launchd(job_id)))


@main.command("status")
@click.argument("job_id")
def status_command(job_id: str) -> None:
    """Show launchd status for a job."""
    if sys.platform.startswith("linux"):
        click.echo(status_job_systemd(job_id))
        return
    click.echo(status_job_launchd(job_id))


@main.command("logs")
@click.argument("job_id")
@click.option(
    "--paths",
    is_flag=True,
    help="Print log paths or journalctl commands instead of log contents.",
)
@click.option(
    "--follow",
    "follow_logs",
    is_flag=True,
    help="Follow logs after printing recent entries.",
)
@click.option(
    "--lines",
    "line_count",
    type=int,
    default=DEFAULT_LOG_LINES,
    show_default=True,
    help="Number of recent log lines to show.",
)
@click.option(
    "--stream",
    type=click.Choice(["all", "stdout", "stderr"]),
    default="all",
    show_default=True,
    help="Which launchd log stream to show on macOS.",
)
def logs_command(
    job_id: str,
    paths: bool,
    follow_logs: bool,
    line_count: int,
    stream: str,
) -> None:
    """Show logs for a job."""
    if line_count < 1:
        raise click.ClickException("--lines must be >= 1")

    if sys.platform.startswith("linux"):
        service_log_command, path_log_command = logs_job_systemd(job_id)
        if paths:
            click.echo(service_log_command)
            click.echo(path_log_command)
            return
        run_systemd_logs(
            [service_log_command, path_log_command],
            line_count=line_count,
            follow_logs=follow_logs,
        )
        return

    stdout_log_path, stderr_log_path = logs_job_launchd(job_id)
    selected_paths = select_launchd_log_paths(
        stdout_log_path, stderr_log_path, stream=stream
    )
    if paths:
        for _name, log_path in selected_paths:
            click.echo(str(log_path))
        return
    run_launchd_logs(selected_paths, line_count=line_count, follow_logs=follow_logs)


def select_launchd_log_paths(
    stdout_log_path: Path,
    stderr_log_path: Path,
    *,
    stream: str,
) -> list[tuple[str, Path]]:
    if stream == "stdout":
        return [("stdout", stdout_log_path)]
    if stream == "stderr":
        return [("stderr", stderr_log_path)]
    return [("stdout", stdout_log_path), ("stderr", stderr_log_path)]


def run_launchd_logs(
    log_paths: list[tuple[str, Path]],
    *,
    line_count: int,
    follow_logs: bool,
) -> None:
    if follow_logs:
        subprocess.run(
            [
                "tail",
                "-n",
                str(line_count),
                "-F",
                *(str(path) for _name, path in log_paths),
            ],
            check=True,
            text=True,
        )
        return

    for name, log_path in log_paths:
        click.echo()
        click.echo(f"== {name}: {format_display_path(log_path)} ==")
        click.echo()
        if not log_path.exists():
            click.echo("log file does not exist yet")
            continue
        result = subprocess.run(
            ["tail", "-n", str(line_count), str(log_path)],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.stdout:
            click.echo(result.stdout.rstrip("\n"))
        if result.stderr:
            click.echo(result.stderr.rstrip("\n"), err=True)
        if result.returncode != 0:
            raise click.ClickException(f"failed to read {log_path}")


def run_systemd_logs(
    log_commands: list[str], *, line_count: int, follow_logs: bool
) -> None:
    command = ["journalctl", "--user", "-n", str(line_count)]
    if follow_logs:
        command.append("-f")
    for log_command in log_commands:
        unit_name = log_command.rsplit(" -u ", 1)[-1]
        command.extend(["-u", unit_name])
    subprocess.run(command, check=True, text=True)


@main.command("run")
@click.argument("job_id")
def run_command(job_id: str) -> None:
    """Run a configured job dispatch target."""
    run_job(job_id)


if __name__ == "__main__":
    main()
