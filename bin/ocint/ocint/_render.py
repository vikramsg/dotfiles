import csv
import io
import json
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from pydantic import BaseModel


def render_json(value: Any, *, sort_keys: bool = False) -> str:
    return json.dumps(_jsonable(value), indent=2, sort_keys=sort_keys) + "\n"


def render_jsonl(rows: Iterable[Any]) -> str:
    return "".join(json.dumps(_jsonable(row), sort_keys=True) + "\n" for row in rows)


def render_csv(rows: Sequence[Mapping[str, Any]]) -> str:
    flattened = [_flatten(row) for row in rows]
    if not flattened:
        return ""
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=list(flattened[0]))
    writer.writeheader()
    writer.writerows(flattened)
    return output.getvalue()


def render_raw(rows: Sequence[Mapping[str, Any]]) -> str:
    flattened = [_flatten(row) for row in rows]
    if not flattened:
        return ""
    columns = list(flattened[0])
    lines = []
    for row in flattened:
        values = [_raw_value(row.get(column)) for column in columns]
        lines.append(values[0] if len(values) == 1 else "\t".join(values))
    return "\n".join(lines) + "\n"


def render_table(rows: Iterable[Any]) -> str:
    flattened = [_flatten(_row_mapping(row)) for row in rows]
    if not flattened:
        return "No rows\n"
    columns = list(flattened[0])
    widths = {column: max(len(column), *(len(str(row.get(column, ""))) for row in flattened)) for column in columns}
    header = "  ".join(column.upper().ljust(widths[column]) for column in columns)
    divider = "  ".join("-" * widths[column] for column in columns)
    body = ["  ".join(str(row.get(column, "")).ljust(widths[column]) for column in columns) for row in flattened]
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


def _jsonable(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, Mapping):
        return {key: _jsonable(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_jsonable(item) for item in value]
    return value


def _raw_value(value: Any) -> str:
    if value is None:
        return ""
    return str(value)
