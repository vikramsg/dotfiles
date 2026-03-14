from pathlib import Path

import click

from screenshot.clipboard import copy_history_entry, copy_path_to_clipboard, handle_event, list_history
from screenshot.config import get_default_config_file, load_config
from screenshot.state import get_state_file
from screenshot.sync import format_rsync_command, run_sync


@click.group()
def main() -> None:
    """Screenshot domain tool."""


@main.command("watch-path")
def watch_path_command() -> None:
    """Print the screenshot watch path."""
    click.echo(str(load_config().screenshot_dir.resolve()))


@main.group("clipboard")
def clipboard_group() -> None:
    """Clipboard-related screenshot workflows."""


@clipboard_group.command("on-event")
def clipboard_on_event_command() -> None:
    """Handle a screenshot folder event."""
    result = handle_event(load_config(), state_file=get_state_file())
    if result is not None:
        click.echo(str(result))


@clipboard_group.command("list")
def clipboard_list_command() -> None:
    """List copied screenshot history."""
    for entry in list_history(state_file=get_state_file()):
        click.echo(entry)


@clipboard_group.command("copy")
@click.option("--index", type=int, required=True)
def clipboard_copy_command(index: int) -> None:
    """Copy a previous history item back to the clipboard."""
    try:
        entry = copy_history_entry(
            index,
            state_file=get_state_file(),
            copy_to_clipboard=copy_path_to_clipboard,
        )
    except IndexError as exc:
        raise click.ClickException(str(exc)) from exc

    click.echo(entry)


@main.group("sync")
def sync_group() -> None:
    """Screenshot sync workflows."""


@sync_group.command("config-path")
def sync_config_path_command() -> None:
    """Print the screenshot config path."""
    click.echo(str(get_default_config_file()))


@sync_group.command("command")
def sync_command_command() -> None:
    """Print the rsync command that would run."""
    click.echo(format_rsync_command())


@sync_group.command("run")
def sync_run_command() -> None:
    """Run the screenshot sync command."""
    run_sync()


if __name__ == "__main__":
    main()
