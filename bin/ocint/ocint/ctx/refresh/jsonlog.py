import json
import os
import sys
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Any, TextIO


def log_refresh_event(
    event: str, *, level: str = "info", stream: TextIO | None = None, enabled: bool = True, **fields: Any
) -> None:
    """Write one structured refresh diagnostic line without affecting command behavior."""
    if not enabled:
        return
    target = sys.stdout if stream is None else stream
    try:
        target.write(_line(event, level=level, fields=fields))
        target.flush()
    except Exception:
        return


def append_refresh_event(log_path: Path, event: str, *, level: str = "info", **fields: Any) -> None:
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as stream:
            log_refresh_event(event, level=level, stream=stream, **fields)
    except Exception:
        return


def _line(event: str, *, level: str, fields: Mapping[str, Any]) -> str:
    record = {
        "ts": datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        "level": level,
        "event": event,
        "pid": os.getpid(),
    }
    record.update({key: _jsonable(value) for key, value in fields.items()})
    return json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n"


def _jsonable(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, BaseException):
        return str(value) or type(value).__name__
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        return [_jsonable(item) for item in value]
    return value
