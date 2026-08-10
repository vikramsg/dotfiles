import asyncio
import subprocess
import sys
from pathlib import Path

import aiohttp
import click
from sqlalchemy.exc import NoResultFound

from ocint.daemon.config import DaemonConfig, DaemonContext
from ocint.daemon.lch.opencode import (
    PrivateFilePurpose,
    PrivateFileRequirement,
    ensure_private_directory,
    provision_configured_coordinator_runtime,
    upsert_private_environment,
    validate_private_file,
)
from ocint.daemon.lch.render import render_job, render_jobs, render_status
from ocint.daemon.lch.service import attach_to_job
from ocint.daemon.lch.setup import discover, setup
from ocint.daemon.lch.systemd import (
    CoordinatorUnitEnablement,
    SubprocessRunner,
    SystemdLifecycle,
    SystemdPaths,
    discover_ngrok,
    installed_ocint,
)
from ocint.daemon.logging import daemon_log_settings
from ocint.daemon.models import OpenCodeAttachment
from ocint.daemon.pull_request_job import open_pull_request_job_store
from ocint.daemon.slack import authenticate_slack_token, validate_configured_slack_token


def lifecycle(context: DaemonContext) -> SystemdLifecycle:
    return SystemdLifecycle(
        SystemdPaths(
            directory=context.config_home / "systemd" / "user",
            environment_file=context.config_home / "ocint" / "daemon.env",
            config_home=context.config_home,
            data_home=context.data_home,
            state_home=context.state_home,
            daemon_config=context.config_path,
            home=context.home,
            user=context.user,
        ),
        SubprocessRunner(),
    )


@click.group()
def lch() -> None:
    """Provision and operate the local daemon."""


@lch.command("setup")
@click.pass_obj
def setup_command(context: DaemonContext) -> None:
    """Create initial configuration and install the daemon."""
    managed_lifecycle = lifecycle(context)
    executable = installed_ocint()
    if context.config_path.exists() or context.config_path.is_symlink():
        _validate_configuration_inputs(context)
        config = context.config()
        provision_configured_coordinator_runtime(context, config)
        ngrok = discover_ngrok(managed_lifecycle.runner, managed_lifecycle.paths.environment_file)
        enablement = managed_lifecycle.install(executable, config.lifecycle, config.coordinator.ingress.port, ngrok)
        _report_install(context, managed_lifecycle, config, executable, enablement, "reused", modified=False)
        context.output.write(
            f"Environment: reused; path={managed_lifecycle.paths.environment_file}; modified=no",
            nl=True,
        )
        context.output.write(
            f"OpenCode configuration: reused; path={config.opencode.config_file}; modified=no; "
            f"coordinator={config.coordinator.opencode.config_file}; coordinator_modified=yes",
            nl=True,
        )
        return
    managed_lifecycle.validate_host()
    managed_lifecycle.validate_executable(executable)
    discovered = discover(managed_lifecycle.runner, managed_lifecycle, Path.cwd(), context)
    environment_existed = managed_lifecycle.paths.environment_file.exists()
    opencode_config_existed = discovered.paths.effective_opencode_config.exists()
    enablement = setup(discovered, managed_lifecycle)
    config = context.config()
    _report_install(context, managed_lifecycle, config, executable, enablement, "created", modified=True)
    context.output.write(
        f"Environment: {'updated' if environment_existed else 'created'}; "
        f"path={managed_lifecycle.paths.environment_file}; secrets=redacted",
        nl=True,
    )
    context.output.write(
        f"OpenCode configuration: {'updated' if opencode_config_existed else 'created'}; "
        f"path={config.opencode.config_file}; modified=yes",
        nl=True,
    )


@lch.command("apply")
@click.pass_obj
def apply_command(context: DaemonContext) -> None:
    """Apply existing configuration to systemd units."""
    managed_lifecycle = lifecycle(context)
    _validate_configuration_inputs(context)
    config = context.config()
    executable = installed_ocint()
    provision_configured_coordinator_runtime(context, config)
    ngrok = discover_ngrok(managed_lifecycle.runner, managed_lifecycle.paths.environment_file)
    enablement = managed_lifecycle.install(executable, config.lifecycle, config.coordinator.ingress.port, ngrok)
    _report_install(context, managed_lifecycle, config, executable, enablement, "loaded", modified=False)


def _validate_configuration_inputs(context: DaemonContext) -> None:
    validate_private_file(PrivateFileRequirement(path=context.config_path, purpose=PrivateFilePurpose.DAEMON_CONFIG))
    validate_private_file(
        PrivateFileRequirement(
            path=context.config_home / "opencode" / "opencode.json",
            purpose=PrivateFilePurpose.SOURCE_OPENCODE_CONFIG,
        )
    )


@lch.command("slack-token")
@click.pass_obj
def slack_token_command(context: DaemonContext) -> None:
    """Validate and install a Slack bot token from hidden input."""
    token = _read_slack_token()
    if not token.startswith("xoxb-"):
        raise click.ClickException("Slack bot token must start with xoxb-")
    try:
        daemon_config = context.config() if context.config_path.exists() else None
        configured = (
            daemon_config.coordinator.slack if daemon_config is not None and daemon_config.coordinator else None
        )
        auth = asyncio.run(
            validate_configured_slack_token(configured, token)
            if configured is not None
            else authenticate_slack_token(token)
        )
    except (aiohttp.ClientError, RuntimeError, ValueError) as error:
        raise click.ClickException(str(error)) from error
    environment = lifecycle(context).paths.environment_file
    ensure_private_directory(environment.parent)
    upsert_private_environment(environment, {"OCINT_DAEMON_SLACK_BOT_TOKEN": token})
    context.output.write(
        f"Slack token: status=installed; workspace={auth.team_id}; bot_user={auth.user_id}; "
        f"bot_id={auth.bot_id or 'unavailable'}; secret=redacted",
        nl=True,
    )


def _read_slack_token() -> str:
    if sys.stdin.isatty():
        return str(click.prompt("Slack bot token", hide_input=True, type=str)).strip()
    token = sys.stdin.readline().strip()
    if not token:
        raise click.ClickException("Slack bot token is required on stdin")
    return token


@lch.command("uninstall")
@click.pass_obj
def uninstall_command(context: DaemonContext) -> None:
    """Remove systemd units while preserving daemon state."""
    managed_lifecycle = lifecycle(context)
    managed_lifecycle.uninstall()
    context.output.write(
        f"Systemd units: removed; service={managed_lifecycle.paths.service}; timer={managed_lifecycle.paths.timer}; "
        f"coordinator={managed_lifecycle.paths.coordinator_service}; "
        f"ngrok={managed_lifecycle.paths.coordinator_ngrok_service}",
        nl=True,
    )
    context.output.write(
        f"Daemon state: preserved; config={context.config_path}; data={context.data_home / 'ocint'}; "
        f"state={context.state_home / 'ocint'}",
        nl=True,
    )


@lch.command("lifecycle")
@click.pass_obj
def lifecycle_command(context: DaemonContext) -> None:
    """Show timer and service lifecycle status."""
    config = context.config()
    log_settings = daemon_log_settings(context.state_home, config.logging)
    context.output.display(render_status(lifecycle(context).status(log_settings.path), config))


@lch.command("list")
@click.option(
    "limit",
    "--limit",
    type=click.IntRange(min=1),
    default=10,
    show_default=True,
    help="Maximum number of recent jobs to show.",
)
@click.pass_obj
def list_command(context: DaemonContext, limit: int) -> None:
    """List recent daemon jobs."""
    config = context.config()
    if not config.database_path.is_file():
        raise click.ClickException(f"daemon database does not exist: {config.database_path}")
    with open_pull_request_job_store(config.database_path) as jobs:
        context.output.display(render_jobs(jobs.list(limit=limit)))


@lch.command("status")
@click.argument("job_id")
@click.pass_obj
def job_status_command(context: DaemonContext, job_id: str) -> None:
    """Show detailed status for one daemon job."""
    config = context.config()
    if not config.database_path.is_file():
        raise click.ClickException(f"daemon database does not exist: {config.database_path}")
    with open_pull_request_job_store(config.database_path) as jobs:
        try:
            job = jobs.get(job_id)
        except NoResultFound as error:
            raise click.ClickException(f"daemon job not found: {job_id}") from error
        context.output.display(render_job(job))


@lch.command("attach")
@click.argument("job_id")
@click.pass_obj
def attach_command(context: DaemonContext, job_id: str) -> None:
    """Attach to a running job's OpenCode session."""
    managed = lifecycle(context)
    try:
        attachment = asyncio.run(_attachment(context, managed.api_token(), job_id))
        context.output.write(
            f"Attachment: starting; job={job_id}; server={attachment.server_url}; "
            f"session={attachment.session_id}; directory={attachment.directory}",
            nl=True,
        )
        attach_to_job(
            attachment,
            context.config().opencode.executable,
            context.environment,
            managed.runner,
        )
    except subprocess.CalledProcessError as error:
        raise click.ClickException(f"opencode attach exited with status {error.returncode}") from error
    except (aiohttp.ClientError, RuntimeError) as error:
        raise click.ClickException(str(error)) from error


@lch.command("logs")
@click.option("lines", "--lines", type=click.IntRange(min=1), default=100)
@click.option("follow", "--follow", is_flag=True)
@click.pass_obj
def logs_command(context: DaemonContext, lines: int, follow: bool) -> None:
    """Read or follow the daemon log."""
    settings = daemon_log_settings(context.state_home, context.config().logging)
    managed = lifecycle(context)
    context.output.write(
        f"Log: reading; path={settings.path}; lines={lines}; follow={'yes' if follow else 'no'}",
        stderr=True,
        nl=True,
    )
    try:
        if follow:
            for text in managed.follow_logs(settings, lines):
                context.output.write(text, nl=False)
        else:
            context.output.write(managed.logs(settings, lines), nl=False)
    except RuntimeError as error:
        raise click.ClickException(str(error)) from error
    except KeyboardInterrupt:
        return


async def _attachment(context: DaemonContext, token: str, job_id: str) -> OpenCodeAttachment:
    config = context.config()
    host = "127.0.0.1" if config.api.host in {"0.0.0.0", "::"} else config.api.host
    url = f"http://{host}:{config.api.port}/api/jobs/{job_id}/attach"
    async with (
        aiohttp.ClientSession(headers={"Authorization": f"Bearer {token}"}) as client,
        client.get(url) as response,
    ):
        if response.status >= 400:
            payload = await response.json()
            raise RuntimeError(f"daemon HTTP {response.status}: {payload.get('detail', 'attach failed')}")
        return OpenCodeAttachment.model_validate(await response.json())


def _report_install(
    context: DaemonContext,
    managed: SystemdLifecycle,
    config: DaemonConfig,
    executable: Path,
    enablement: CoordinatorUnitEnablement,
    configuration_outcome: str,
    *,
    modified: bool,
) -> None:
    context.output.write(
        f"Configuration: {configuration_outcome}; path={context.config_path}; modified={'yes' if modified else 'no'}",
        nl=True,
    )
    context.output.write(
        f"Systemd service: regenerated; path={managed.paths.service}; executable={executable.resolve()}",
        nl=True,
    )
    context.output.write(
        f"Systemd coordinator services: regenerated; coordinator={managed.paths.coordinator_service}; "
        f"coordinator_state={enablement.coordinator}; ngrok={managed.paths.coordinator_ngrok_service}; "
        f"ngrok_state={enablement.ngrok}",
        nl=True,
    )
    context.output.write(
        f"Systemd timer: enabled; path={managed.paths.timer}; "
        f"startup_delay_seconds={config.lifecycle.startup_delay_seconds}; "
        f"inactive_interval_seconds={config.lifecycle.inactive_interval_seconds}",
        nl=True,
    )
