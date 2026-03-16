import sys
import json

import click

from lch.config import get_config_file, load_config
from lch.launchd import (
    discover_launchd_jobs,
    format_display_path,
    get_launchagents_directory,
    get_lch_executable_path,
    get_logs_directory,
    get_standard_launchd_roots,
    install_job,
    list_known_jobs,
    logs_job,
    paginate_launchd_jobs,
    render_full_launchd_job_list as render_full_launchd_job_list_from_launchd,
    run_job,
    status_job,
    uninstall_job,
)


@click.group()
def main() -> None:
    """Thin launchd orchestrator."""


@main.command("list")
def list_command() -> None:
    """List known lch jobs and their local status."""
    click.echo("JOB  INSTALLED  LOADED  LABEL")
    for job in list_known_jobs():
        installed = "yes" if job.installed else "no"
        loaded = "yes" if job.loaded else "no"
        click.echo(f"{job.job_id}  {installed}  {loaded}  {job.label}")


def render_lch_config() -> str:
    config_file = get_config_file()
    config = load_config()
    example = {
        "namespace": "com.vikramsg.dotfiles",
    }
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
            json.dumps(example, indent=2),
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
    paginated = paginate_launchd_jobs(discover_launchd_jobs(), page=page, page_size=page_size)
    lines = [f"PAGE {paginated.page}/{paginated.total_pages}  TOTAL {paginated.total_items}  PAGE_SIZE {paginated.page_size}", "", "LABEL  TYPE  LOADED  SOURCE"]
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
    click.echo(str(install_job(job_id)))


@main.command("uninstall")
@click.argument("job_id")
def uninstall_command(job_id: str) -> None:
    """Uninstall a launchd job."""
    click.echo(str(uninstall_job(job_id)))


@main.command("status")
@click.argument("job_id")
def status_command(job_id: str) -> None:
    """Show launchd status for a job."""
    click.echo(status_job(job_id))


@main.command("logs")
@click.argument("job_id")
def logs_command(job_id: str) -> None:
    """Show launchd log file paths for a job."""
    stdout_log_path, stderr_log_path = logs_job(job_id)
    click.echo(str(stdout_log_path))
    click.echo(str(stderr_log_path))


@main.command("run")
@click.argument("job_id")
def run_command(job_id: str) -> None:
    """Run a configured job dispatch target."""
    run_job(job_id)


if __name__ == "__main__":
    main()
