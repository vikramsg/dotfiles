import sqlite3
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from opencode_state.models import DailyUsage, ModelUsage, SessionUsage, UsageSummary, UsageTokens


TOKEN_SELECT = """
COALESCE(SUM(CAST(json_extract(part.data, '$.tokens.input') AS INTEGER)), 0) AS input,
COALESCE(SUM(CAST(json_extract(part.data, '$.tokens.output') AS INTEGER)), 0) AS output,
COALESCE(SUM(CAST(json_extract(part.data, '$.tokens.reasoning') AS INTEGER)), 0) AS reasoning,
COALESCE(SUM(CAST(json_extract(part.data, '$.tokens.cache.read') AS INTEGER)), 0) AS cache_read,
COALESCE(SUM(CAST(json_extract(part.data, '$.tokens.cache.write') AS INTEGER)), 0) AS cache_write,
COALESCE(
  SUM(
    COALESCE(
      CAST(json_extract(part.data, '$.tokens.total') AS INTEGER),
      COALESCE(CAST(json_extract(part.data, '$.tokens.input') AS INTEGER), 0)
      + COALESCE(CAST(json_extract(part.data, '$.tokens.output') AS INTEGER), 0)
      + COALESCE(CAST(json_extract(part.data, '$.tokens.reasoning') AS INTEGER), 0)
      + COALESCE(CAST(json_extract(part.data, '$.tokens.cache.read') AS INTEGER), 0)
      + COALESCE(CAST(json_extract(part.data, '$.tokens.cache.write') AS INTEGER), 0)
    )
  ),
  0
) AS total
"""


@dataclass(frozen=True)
class UsageWindow:
    since: date | None = None
    until: date | None = None
    start_ms: int | None = None
    end_ms: int | None = None

    @property
    def label(self) -> str:
        if self.since is None and self.until is None:
            return "all"
        start = self.since.isoformat() if self.since else "beginning"
        end = self.until.isoformat() if self.until else "now"
        return f"{start}..{end}"


def parse_yyyy_mm_dd(value: str | None) -> date | None:
    if value is None:
        return None
    return date.fromisoformat(value)


def make_window(*, since: str | None = None, until: str | None = None, days: int | None = None) -> UsageWindow:
    since_date = parse_yyyy_mm_dd(since)
    until_date = parse_yyyy_mm_dd(until)
    if days is not None:
        if days <= 0:
            raise ValueError("--days must be greater than zero")
        if since_date is None:
            anchor_date = until_date or datetime.now(UTC).date()
            since_date = anchor_date - timedelta(days=days - 1)

    if since_date is not None and until_date is not None and since_date > until_date:
        raise ValueError("--since must be on or before --until")

    start_ms = _start_of_day_ms(since_date) if since_date else None
    end_ms = _start_of_day_ms(until_date + timedelta(days=1)) if until_date else None
    return UsageWindow(since=since_date, until=until_date, start_ms=start_ms, end_ms=end_ms)


def summarize_usage(connection: sqlite3.Connection, *, db_path: Path, window: UsageWindow) -> UsageSummary:
    row = connection.execute(
        f"""
        SELECT
          COUNT(DISTINCT part.session_id) AS sessions,
          COUNT(*) AS llm_steps,
          COALESCE(SUM(CAST(json_extract(part.data, '$.cost') AS REAL)), 0.0) AS cost,
          {TOKEN_SELECT}
        FROM part
        WHERE {step_finish_where(window)}
        """,
        window_params(window),
    ).fetchone()
    return UsageSummary(
        db_path=db_path,
        since=window.since,
        until=window.until,
        sessions=int(row["sessions"] or 0),
        llm_steps=int(row["llm_steps"] or 0),
        cost=float(row["cost"] or 0.0),
        tokens=_tokens_from_row(row),
    )


def daily_usage(connection: sqlite3.Connection, *, window: UsageWindow) -> list[DailyUsage]:
    rows = connection.execute(
        f"""
        SELECT
          date(part.time_created / 1000, 'unixepoch') AS day,
          COUNT(DISTINCT part.session_id) AS sessions,
          COUNT(*) AS llm_steps,
          COALESCE(SUM(CAST(json_extract(part.data, '$.cost') AS REAL)), 0.0) AS cost,
          {TOKEN_SELECT}
        FROM part
        WHERE {step_finish_where(window)}
        GROUP BY day
        ORDER BY day
        """,
        window_params(window),
    ).fetchall()
    return [
        DailyUsage(
            day=row["day"],
            sessions=int(row["sessions"] or 0),
            llm_steps=int(row["llm_steps"] or 0),
            cost=float(row["cost"] or 0.0),
            tokens=_tokens_from_row(row),
        )
        for row in rows
    ]


def model_usage(connection: sqlite3.Connection, *, window: UsageWindow) -> list[ModelUsage]:
    rows = connection.execute(
        f"""
        SELECT
          COALESCE(json_extract(message.data, '$.providerID'), '(unknown)') AS provider,
          COALESCE(json_extract(message.data, '$.modelID'), '(unknown)') AS model,
          COUNT(DISTINCT part.session_id) AS sessions,
          COUNT(*) AS llm_steps,
          COALESCE(SUM(CAST(json_extract(part.data, '$.cost') AS REAL)), 0.0) AS cost,
          {TOKEN_SELECT}
        FROM part
        LEFT JOIN message ON message.id = part.message_id
        WHERE {step_finish_where(window)}
        GROUP BY provider, model
        ORDER BY cost DESC, llm_steps DESC, provider, model
        """,
        window_params(window),
    ).fetchall()
    return [
        ModelUsage(
            provider=str(row["provider"]),
            model=str(row["model"]),
            sessions=int(row["sessions"] or 0),
            llm_steps=int(row["llm_steps"] or 0),
            cost=float(row["cost"] or 0.0),
            tokens=_tokens_from_row(row),
        )
        for row in rows
    ]


def session_usage(connection: sqlite3.Connection, *, window: UsageWindow) -> list[SessionUsage]:
    rows = connection.execute(
        f"""
        SELECT
          part.session_id,
          strftime('%Y-%m-%dT%H:%M:%SZ', MIN(part.time_created) / 1000, 'unixepoch') AS first_seen,
          strftime('%Y-%m-%dT%H:%M:%SZ', MAX(part.time_created) / 1000, 'unixepoch') AS last_seen,
          COUNT(*) AS llm_steps,
          COALESCE(SUM(CAST(json_extract(part.data, '$.cost') AS REAL)), 0.0) AS cost,
          {TOKEN_SELECT}
        FROM part
        WHERE {step_finish_where(window)}
        GROUP BY part.session_id
        ORDER BY MAX(part.time_created) DESC, part.session_id
        """,
        window_params(window),
    ).fetchall()
    return [
        SessionUsage(
            session_id=str(row["session_id"]),
            first_seen=str(row["first_seen"]),
            last_seen=str(row["last_seen"]),
            llm_steps=int(row["llm_steps"] or 0),
            cost=float(row["cost"] or 0.0),
            tokens=_tokens_from_row(row),
        )
        for row in rows
    ]


def step_finish_where(window: UsageWindow) -> str:
    clauses = ["json_extract(part.data, '$.type') = 'step-finish'"]
    if window.start_ms is not None:
        clauses.append("part.time_created >= :start_ms")
    if window.end_ms is not None:
        clauses.append("part.time_created < :end_ms")
    return " AND ".join(clauses)


def window_params(window: UsageWindow) -> dict[str, int]:
    params: dict[str, int] = {}
    if window.start_ms is not None:
        params["start_ms"] = window.start_ms
    if window.end_ms is not None:
        params["end_ms"] = window.end_ms
    return params


def _start_of_day_ms(value: date) -> int:
    return int(datetime.combine(value, datetime.min.time(), tzinfo=UTC).timestamp() * 1000)


def _tokens_from_row(row: Any) -> UsageTokens:
    return UsageTokens(
        input=int(row["input"] or 0),
        output=int(row["output"] or 0),
        reasoning=int(row["reasoning"] or 0),
        cache_read=int(row["cache_read"] or 0),
        cache_write=int(row["cache_write"] or 0),
        total=int(row["total"] or 0),
    )
