import os
from pathlib import Path

import click

from ocint._models import CliContext
from ocint.daemon.lch.provision import discover, provision
from ocint.daemon.lch.systemd import SubprocessRunner, SystemdLifecycle, SystemdPaths, installed_ocint


def lifecycle(home: Path) -> SystemdLifecycle:
    config_home = Path(os.environ.get("XDG_CONFIG_HOME", home / ".config"))
    data_home = Path(os.environ.get("XDG_DATA_HOME", home / ".local" / "share"))
    return SystemdLifecycle(
        SystemdPaths(
            directory=config_home / "systemd" / "user",
            environment_file=config_home / "ocint" / "daemon.env",
            config_home=config_home,
            data_home=data_home,
            daemon_config=config_home / "ocint" / "daemon.toml",
            home=home,
        ),
        SubprocessRunner(),
    )


@click.group()
def lch() -> None:
    """Provision and operate the user systemd lifecycle."""


@lch.command("provision")
@click.pass_obj
def provision_command(context: CliContext) -> None:
    home = Path.home()
    managed_lifecycle = lifecycle(home)
    managed_lifecycle.validate_host()
    managed_lifecycle.validate_executable(installed_ocint())
    discovered = discover(managed_lifecycle.runner, managed_lifecycle, Path.cwd(), home)
    provision(discovered, managed_lifecycle)
    context.output.write("ocint daemon provisioned; the systemd timer will start it", nl=True)


@lch.command("install")
def install_command() -> None:
    lifecycle(Path.home()).install(installed_ocint())


@lch.command("uninstall")
def uninstall_command() -> None:
    lifecycle(Path.home()).uninstall()


@lch.command("status")
@click.pass_obj
def status_command(context: CliContext) -> None:
    context.output.write(lifecycle(Path.home()).status(), nl=True)


@lch.command("logs")
@click.option("lines", "--lines", type=click.IntRange(min=1), default=100)
@click.option("follow", "--follow", is_flag=True)
@click.pass_obj
def logs_command(context: CliContext, lines: int, follow: bool) -> None:
    context.output.write(lifecycle(Path.home()).logs(lines, follow), nl=False)
