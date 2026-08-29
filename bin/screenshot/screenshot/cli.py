import json
from pathlib import Path

import click

from screenshot.clipboard import copy_history_entry, copy_path_to_clipboard, handle_event, list_history
from screenshot.config import get_config_file, load_config
from screenshot.macos import apply_macos_screenshot_location
from screenshot.paths import format_user_path
from screenshot.state import get_state_file
from screenshot.sync import format_rsync_command, get_sync_source, run_sync


@click.group()
def main() -> None:
    """Screenshot domain tool."""


def render_screenshot_config() -> str:
    config_file = get_config_file()
    state_file = get_state_file()
    config = load_config()
    example = {
        "screenshot_dir": "~/Desktop/Screenshots",
        "clipboard_history_limit": 5,
        "sync": {
            "sources": [
                {
                    "id": "system",
                    "local_dir": "~/Desktop/Screenshots",
                    "vm_host": "my-vm",
                    "remote_dir": "~/Desktop/Screenshots/",
                    "include": ["Screenshot *.png", "Screen Shot *.png"],
                }
            ]
        },
    }
    lines = [
        f"CONFIG_FILE  {config_file}",
        f"STATE_FILE  {state_file}",
        f"SCREENSHOT_DIR  {config.screenshot_dir}",
        "MACOS_APPLY  screenshot macos apply",
        "",
        "FORMAT",
        json.dumps(example, indent=2),
    ]
    return "\n".join(lines)


@main.command("config")
def config_command() -> None:
    """Show the effective screenshot config paths and format."""
    click.echo(render_screenshot_config())


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
        click.echo(format_user_path(result))


@clipboard_group.command("list")
def clipboard_list_command() -> None:
    """List copied screenshot history."""
    for entry in list_history(state_file=get_state_file()):
        click.echo(format_user_path(entry))


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
    click.echo(str(get_config_file()))


@sync_group.command("command")
@click.argument("source_id", required=False, default="system")
def sync_command_command(source_id: str) -> None:
    """Print the rsync command that would run."""
    try:
        click.echo(format_rsync_command(source_id))
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc


@sync_group.command("run")
@click.argument("source_id", required=False, default="system")
def sync_run_command(source_id: str) -> None:
    """Run the screenshot sync command."""
    try:
        run_sync(source_id)
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc


@sync_group.command("watch-path")
@click.argument("source_id")
def sync_watch_path_command(source_id: str) -> None:
    """Print the watched local path for one sync source."""
    try:
        click.echo(str(get_sync_source(source_id).local_dir.resolve()))
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc


@main.group("macos")
def macos_group() -> None:
    """Apply screenshot config to macOS system settings."""


@macos_group.command("apply")
def macos_apply_command() -> None:
    """Set the macOS screenshot location from screenshot config."""
    try:
        click.echo(str(apply_macos_screenshot_location()))
    except RuntimeError as exc:
        raise click.ClickException(str(exc)) from exc
if __name__ == "__main__":
    main()
