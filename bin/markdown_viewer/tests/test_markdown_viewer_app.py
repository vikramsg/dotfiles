from __future__ import annotations

import asyncio
from pathlib import Path

from textual.widgets import MarkdownViewer

try:
    from markdown_viewer.app import MarkdownViewerApp
except ModuleNotFoundError:
    from bin.markdown_viewer.markdown_viewer.app import MarkdownViewerApp


def test_markdown_viewer_renders_string_input_and_exports_svg() -> None:
    async def run_test() -> None:
        app = MarkdownViewerApp(
            markdown_text=(
                "# Demo\n\n"
                "- item\n\n"
                "| Name | Value |\n"
                "| ---- | ----- |\n"
                "| foo | bar |\n\n"
                "```python\n"
                "print('hi')\n"
                "```\n"
            ),
            show_table_of_contents=False,
        )

        async with app.run_test() as pilot:
            await pilot.pause()
            viewer = pilot.app.query_one(MarkdownViewer)

            assert viewer.show_table_of_contents is False
            assert [item[:2] for item in viewer.document.table_of_contents] == [(1, "Demo")]

            screenshot_svg = pilot.app.export_screenshot()

        assert "Demo" in screenshot_svg
        assert "item" in screenshot_svg
        assert "foo" in screenshot_svg
        assert "bar" in screenshot_svg
        assert "print" in screenshot_svg

    asyncio.run(run_test())


def test_markdown_viewer_loads_file_input(tmp_path: Path) -> None:
    async def run_test() -> None:
        markdown_file = tmp_path / "guide.md"
        markdown_file.write_text("# Guide\n\nSee the list.\n")

        app = MarkdownViewerApp(source_path=markdown_file)

        async with app.run_test() as pilot:
            await pilot.pause()
            viewer = pilot.app.query_one(MarkdownViewer)

            assert viewer.document.source == "# Guide\n\nSee the list.\n"
            assert [item[:2] for item in viewer.document.table_of_contents] == [(1, "Guide")]

    asyncio.run(run_test())
