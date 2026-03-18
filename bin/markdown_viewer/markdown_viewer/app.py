from __future__ import annotations

from pathlib import Path

from textual.app import App, ComposeResult
from textual.widgets import Footer, MarkdownViewer


class MarkdownViewerApp(App[None]):
    """Render Markdown content in a Textual app."""

    BINDINGS = [("q", "quit", "Quit")]

    def __init__(
        self,
        *,
        source_path: Path | None = None,
        markdown_text: str | None = None,
        show_table_of_contents: bool = True,
        open_links: bool = True,
    ) -> None:
        super().__init__()
        self._source_path = source_path
        self._markdown_text = markdown_text
        self._show_table_of_contents = show_table_of_contents
        self._open_links = open_links
        self.title = source_path.name if source_path is not None else "markdown-viewer"

    def compose(self) -> ComposeResult:
        yield MarkdownViewer(
            show_table_of_contents=self._show_table_of_contents,
            open_links=self._open_links,
        )
        yield Footer()

    async def on_mount(self) -> None:
        viewer = self.query_one(MarkdownViewer)
        if self._source_path is not None:
            await viewer.go(self._source_path)
            return

        await viewer.document.update(self._markdown_text or "")
