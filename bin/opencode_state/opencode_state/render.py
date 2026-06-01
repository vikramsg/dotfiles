from collections.abc import Iterable, Mapping
from typing import Any

from pydantic import BaseModel

from opencode_state.models import ResolvedPaths, UsageSummary
from opencode_state.stats import UsageWindow


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


def render_summary(summary: UsageSummary, window: UsageWindow) -> str:
    return "\n".join(
        [
            f"DB: {summary.db_path}",
            f"WINDOW: {window.label}",
            f"SESSIONS: {_format_int(summary.sessions)}",
            f"LLM_STEPS: {_format_int(summary.llm_steps)}",
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


def _format_int(value: int) -> str:
    return f"{value:,}"


def render_rows(rows: Iterable[Any]) -> str:
    flattened = [_flatten(_row_mapping(row)) for row in rows]
    if not flattened:
        return "No rows\n"
    columns = list(flattened[0])
    widths = {
        column: max(len(column), *(len(str(row.get(column, ""))) for row in flattened))
        for column in columns
    }
    header = "  ".join(column.upper().ljust(widths[column]) for column in columns)
    divider = "  ".join("-" * widths[column] for column in columns)
    body = [
        "  ".join(str(row.get(column, "")).ljust(widths[column]) for column in columns)
        for row in flattened
    ]
    return "\n".join([header, divider, *body, ""])


def _row_mapping(value: Any) -> Mapping[str, Any]:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, Mapping):
        return value
    raise TypeError(f"Expected row mapping or Pydantic model, got {type(value).__name__}")


def _flatten(value: Mapping[str, Any]) -> dict[str, Any]:
    flattened: dict[str, Any] = {}
    for key, item in value.items():
        if isinstance(item, Mapping):
            for nested_key, nested_value in item.items():
                flattened[f"{key}_{nested_key}"] = nested_value
        else:
            flattened[key] = item
    return flattened
