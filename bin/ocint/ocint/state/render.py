from collections.abc import Iterable
from typing import Any

from ocint._models import ResolvedPaths
from ocint._render import render_table
from ocint._timeutil import UsageWindow
from ocint.state.models import StateSummary


def render_paths(paths: ResolvedPaths) -> str:
    return "\n".join(
        [
            f"CONFIG: {paths.config_path}",
            f"CONFIG_EXISTS: {paths.config_exists}",
            f"DB: {paths.db_path}",
            f"DB_EXISTS: {paths.db_exists}",
            "",
        ]
    )


def render_summary(summary: StateSummary, window: UsageWindow) -> str:
    return "\n".join(
        [
            f"DB: {summary.db_path}",
            f"WINDOW: {window.label}",
            f"SESSIONS: {_format_int(summary.sessions)}",
            f"MESSAGES: {_format_int(summary.messages)}",
            f"COST: {summary.cost:.6f}",
            f"TOKENS_INPUT: {_format_int(summary.tokens.input)}",
            f"TOKENS_OUTPUT: {_format_int(summary.tokens.output)}",
            f"TOKENS_REASONING: {_format_int(summary.tokens.reasoning)}",
            f"TOKENS_CACHE_READ: {_format_int(summary.tokens.cache_read)}",
            f"TOKENS_CACHE_WRITE: {_format_int(summary.tokens.cache_write)}",
            f"TOKENS_TOTAL: {_format_int(summary.tokens.total)}",
            "",
        ]
    )


def render_rows(rows: Iterable[Any]) -> str:
    return render_table(rows)


def _format_int(value: int) -> str:
    return f"{value:,}"
