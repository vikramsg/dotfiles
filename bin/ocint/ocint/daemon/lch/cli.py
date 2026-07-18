from pathlib import Path

import click

from ocint.daemon.config import DaemonContext
from ocint.daemon.lch.provision import discover, provision
from ocint.daemon.lch.render import render_status
from ocint.daemon.lch.systemd import SubprocessRunner, SystemdLifecycle, SystemdPaths, installed_ocint
from ocint.daemon.logging import daemon_log_settings


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
    """Provision and operate the user systemd lifecycle."""


@lch.command("provision")
@click.pass_obj
def provision_command(context: DaemonContext) -> None:
    managed_lifecycle = lifecycle(context)
    managed_lifecycle.validate_host()
    managed_lifecycle.validate_executable(installed_ocint())
    discovered = discover(managed_lifecycle.runner, managed_lifecycle, Path.cwd(), context)
    provision(discovered, managed_lifecycle, context)
    context.output.write("ocint daemon provisioned; the systemd timer will start it", nl=True)


@lch.command("install")
@click.pass_obj
def install_command(context: DaemonContext) -> None:
    lifecycle(context).install(installed_ocint(), context.config().lifecycle)


@lch.command("uninstall")
@click.pass_obj
def uninstall_command(context: DaemonContext) -> None:
    lifecycle(context).uninstall()


@lch.command("status")
@click.pass_obj
def status_command(context: DaemonContext) -> None:
    config = context.config()
    log_settings = daemon_log_settings(context.state_home, config.logging)
    context.output.display(render_status(lifecycle(context).status(log_settings.path), config))


@lch.command("logs")
@click.option("lines", "--lines", type=click.IntRange(min=1), default=100)
@click.option("follow", "--follow", is_flag=True)
@click.pass_obj
def logs_command(context: DaemonContext, lines: int, follow: bool) -> None:
    settings = daemon_log_settings(context.state_home, context.config().logging)
    managed = lifecycle(context)
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
