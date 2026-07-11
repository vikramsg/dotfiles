from collections.abc import Iterable, Sequence

from rich.console import Group, RenderableType
from rich.rule import Rule
from rich.table import Table
from rich.text import Text

type Presentation = RenderableType


def document(title: str, *content: Presentation) -> Presentation:
    """Compose a titled human-readable document."""
    return Group(Text(title, style="bold green"), Text(""), *content)


def key_value_section(title: str, rows: Sequence[tuple[str, object]]) -> Presentation:
    """Render aligned labelled values."""
    table = Table.grid(padding=(0, 2))
    table.add_column(style="bold", no_wrap=True)
    table.add_column(overflow="fold")
    for label, value in rows:
        table.add_row(Text(f"{label}:"), Text("" if value is None else str(value)))
    return Group(Rule(title, style="cyan", align="left"), Text(""), table, Text(""))


def data_table(
    title: str,
    columns: Sequence[str],
    rows: Iterable[Sequence[object]],
    *,
    empty_message: str = "No rows",
) -> Presentation:
    """Render readable tabular data with an explicit empty state."""
    table = Table(show_edge=False, box=None, pad_edge=False, header_style="bold")
    for column in columns:
        table.add_column(column, overflow="fold")
    row_count = 0
    for row in rows:
        table.add_row(*(Text("" if value is None else str(value)) for value in row))
        row_count += 1
    content: Presentation = table if row_count else Text(empty_message, style="dim")
    return Group(Rule(title, style="cyan", align="left"), Text(""), content, Text(""))
