import json
import os
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import TextIO

import structlog
from structlog.typing import EventDict, FilteringBoundLogger, WrappedLogger

from ocint.ctx.models import (
    CtxRefreshLogs,
    CtxRefreshLogsAvailable,
    CtxRefreshLogsUnavailable,
    CtxRefreshRawLogEntry,
    CtxRefreshStructuredLogEntry,
)


def create_refresh_logger(*, run_id: str, stream: TextIO | None = None, enabled: bool = True) -> FilteringBoundLogger:
    """Create one configured structured logger for a refresh run."""
    return structlog.wrap_logger(
        structlog.PrintLogger(sys.stdout if stream is None else stream),
        wrapper_class=structlog.make_filtering_bound_logger(0 if enabled else 50),
        processors=[
            structlog.processors.TimeStamper(fmt="iso", utc=True, key="ts"),
            structlog.processors.add_log_level,
            _add_pid,
            structlog.processors.JSONRenderer(separators=(",", ":")),
        ],
        run_id=run_id,
    )


@contextmanager
def open_refresh_logger(log_path: Path, *, run_id: str) -> Iterator[FilteringBoundLogger]:
    """Open the refresh JSONL artifact and bind one logger to its run."""
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as stream:
        yield create_refresh_logger(run_id=run_id, stream=stream)


def read_refresh_logs(log_path: Path) -> CtxRefreshLogs:
    if not log_path.exists():
        return CtxRefreshLogsUnavailable(path=log_path, message="Refresh log does not exist.")
    try:
        lines = log_path.read_text(encoding="utf-8").splitlines()
    except OSError as error:
        return CtxRefreshLogsUnavailable(path=log_path, message=f"Refresh log could not be read: {error}")
    if not lines:
        return CtxRefreshLogsUnavailable(path=log_path, message="Refresh log is empty.")

    entries: list[CtxRefreshStructuredLogEntry | CtxRefreshRawLogEntry] = []
    for line in lines:
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            entries.append(CtxRefreshRawLogEntry(text=line))
            continue
        if not isinstance(record, dict):
            entries.append(CtxRefreshRawLogEntry(text=line))
            continue
        event = record.get("event")
        run_id = record.get("run_id")
        if not isinstance(event, str) or not isinstance(run_id, str):
            entries.append(CtxRefreshRawLogEntry(text=line))
            continue
        entries.append(CtxRefreshStructuredLogEntry(json_line=line, event=event, run_id=run_id))
    return CtxRefreshLogsAvailable(path=log_path, entries=entries)


def _add_pid(_logger: WrappedLogger, _method_name: str, event_dict: EventDict) -> EventDict:
    event_dict.setdefault("pid", os.getpid())
    return event_dict
