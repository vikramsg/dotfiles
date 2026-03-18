from __future__ import annotations

import sys
from pathlib import Path
from typing import TextIO

import click

from .app import MarkdownViewerApp


def resolve_source(source: str | None, stdin: TextIO) -> tuple[Path | None, str | None]:
    """Resolve a file path or stdin payload into app input."""
    if source is None:
        if stdin.isatty():
            raise click.ClickException(
                "Provide a Markdown file path or pipe Markdown on stdin."
            )
        markdown_text = stdin.read()
        if not markdown_text.strip():
            raise click.ClickException("No Markdown received on stdin.")
        return None, markdown_text

    if source == "-":
        markdown_text = stdin.read()
        if not markdown_text.strip():
            raise click.ClickException("No Markdown received on stdin.")
        return None, markdown_text

    path = Path(source).expanduser()
    if not path.exists():
        raise click.ClickException(f"Markdown source not found: {path}")
    if path.is_dir():
        raise click.ClickException(f"Markdown source must be a file: {path}")
    return path, None


def launch_markdown_viewer(
    *,
    source_path: Path | None,
    markdown_text: str | None,
    show_table_of_contents: bool,
    open_links: bool,
) -> None:
    """Launch the Textual markdown viewer app."""
    app = MarkdownViewerApp(
        source_path=source_path,
        markdown_text=markdown_text,
        show_table_of_contents=show_table_of_contents,
        open_links=open_links,
    )
    app.run()


@click.command()
@click.argument("source", required=False)
@click.option("--toc/--no-toc", "show_table_of_contents", default=True)
@click.option("--links/--no-links", "open_links", default=True)
def main(source: str | None, show_table_of_contents: bool, open_links: bool) -> None:
    """Render a Markdown document in Textual."""
    source_path, markdown_text = resolve_source(source, sys.stdin)
    launch_markdown_viewer(
        source_path=source_path,
        markdown_text=markdown_text,
        show_table_of_contents=show_table_of_contents,
        open_links=open_links,
    )


if __name__ == "__main__":
    main()
