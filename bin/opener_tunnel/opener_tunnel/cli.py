import logging
import subprocess
import threading

import click

from opener_tunnel.config import ConfigError, build_ssh_argv, load_config
from opener_tunnel.server import UnixSocketServer
from opener_tunnel.supervisor import Supervisor, TmuxController, stop_on_signals


@click.group()
def main() -> None:
    """Supervise a configured browser-opener tunnel."""


@main.command("run")
def run_command() -> None:
    """Run the foreground socket and tmux supervisor."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    try:
        config = load_config()
        logging.getLogger(__name__).info("configuration loaded")
        server = UnixSocketServer(config.socket_path, config.browser.command)
        tmux = TmuxController(
            config.tmux.session,
            config.tmux.command,
            build_ssh_argv(config),
        )
        stop_event = threading.Event()
        with stop_on_signals(stop_event):
            exit_code = Supervisor(server, tmux, stop_event).run()
    except (ConfigError, OSError, RuntimeError, subprocess.SubprocessError) as exc:
        raise click.ClickException(str(exc)) from exc
    if exit_code:
        raise click.ClickException("configured tmux process exited")


if __name__ == "__main__":
    main()
