import click

from ocint.cli._render import default_cli_context
from ocint.ctx.cli import ctx
from ocint.state.cli import state


@click.group()
@click.pass_context
def main(click_ctx: click.Context) -> None:
    """OpenCode local SQLite intelligence tools."""
    if click_ctx.obj is None:
        click_ctx.obj = default_cli_context()


main.add_command(state)
main.add_command(ctx)
