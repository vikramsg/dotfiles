import click

from ocint.ctx.cli import ctx
from ocint.state.cli import state


@click.group()
def main() -> None:
    """OpenCode local SQLite intelligence tools."""


main.add_command(state)
main.add_command(ctx)
