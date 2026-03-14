import click

from lch.launchd import install_job, logs_job, run_job, status_job, uninstall_job


@click.group()
def main() -> None:
    """Thin launchd orchestrator."""


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
