"""Shared presentation API for ocint.

Feature renderers and CLI modules import reusable presentation components,
terminal output construction, and exact machine-output serializers from this
package facade. Private modules within this package are implementation details
and must not be imported directly.
"""

from rich.console import Group
from rich.markdown import Markdown
from rich.rule import Rule
from rich.table import Table
from rich.text import Text

from ocint.presentation._components import Presentation, data_table, document, key_value_section
from ocint.presentation._output import default_cli_context
from ocint.presentation._serialization import plain_table, render_csv, render_json, render_jsonl, render_raw

__all__ = [
    "Group",
    "Markdown",
    "Presentation",
    "Rule",
    "Table",
    "Text",
    "data_table",
    "default_cli_context",
    "document",
    "key_value_section",
    "plain_table",
    "render_csv",
    "render_json",
    "render_jsonl",
    "render_raw",
]
