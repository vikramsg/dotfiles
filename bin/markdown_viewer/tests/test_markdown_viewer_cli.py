from __future__ import annotations

from io import StringIO
from pathlib import Path
from unittest.mock import patch

import click
from click.testing import CliRunner

try:
    from markdown_viewer import cli as cli_module
except ModuleNotFoundError:
    from bin.markdown_viewer.markdown_viewer import cli as cli_module

main = cli_module.main
resolve_source = cli_module.resolve_source


class FakeStdin(StringIO):
    def __init__(self, value: str, *, is_tty: bool) -> None:
        super().__init__(value)
        self._is_tty = is_tty

    def isatty(self) -> bool:
        return self._is_tty


def test_resolve_source_accepts_existing_file(tmp_path: Path) -> None:
    markdown_file = tmp_path / "demo.md"
    markdown_file.write_text("# Demo\n")

    source_path, markdown_text = resolve_source(
        str(markdown_file), FakeStdin("", is_tty=True)
    )

    assert source_path == markdown_file
    assert markdown_text is None


def test_resolve_source_reads_stdin_when_no_argument() -> None:
    source_path, markdown_text = resolve_source(None, FakeStdin("# Demo\n", is_tty=False))

    assert source_path is None
    assert markdown_text == "# Demo\n"


def test_resolve_source_rejects_missing_input() -> None:
    try:
        resolve_source(None, FakeStdin("", is_tty=True))
    except click.ClickException as exc:
        assert "Provide a Markdown file path" in str(exc)
    else:
        raise AssertionError("expected ClickException")


def test_cli_launches_app_with_file_input(tmp_path: Path) -> None:
    markdown_file = tmp_path / "demo.md"
    markdown_file.write_text("# Demo\n")

    runner = CliRunner()
    with patch.object(cli_module, "launch_markdown_viewer") as launch_mock:
        result = runner.invoke(main, [str(markdown_file), "--no-toc", "--no-links"])

    assert result.exit_code == 0
    launch_mock.assert_called_once_with(
        source_path=markdown_file,
        markdown_text=None,
        show_table_of_contents=False,
        open_links=False,
    )


def test_cli_launches_app_with_stdin_input() -> None:
    runner = CliRunner()
    with patch.object(cli_module, "launch_markdown_viewer") as launch_mock:
        result = runner.invoke(main, ["-"], input="# Demo\n")

    assert result.exit_code == 0
    launch_mock.assert_called_once_with(
        source_path=None,
        markdown_text="# Demo\n",
        show_table_of_contents=True,
        open_links=True,
    )
