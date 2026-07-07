from __future__ import annotations

import argparse
import cProfile
import io
import json
import pstats
import sqlite3
import statistics
import time
from collections.abc import Callable, Iterator, Sequence
from contextlib import closing, contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from ocint._db import open_readonly_connection
from ocint._timeutil import UsageWindow, make_window
from ocint.opencode import schema as opencode_schema
from ocint.opencode.models import OpenCodePartData, OpenCodePartRow
from ocint.opencode.repository import (
    OpenCodeRepository,
    _columns,
    _optional_int,
    _optional_str,
    _parse_payload,
    _quote,
    _session_message_map,
    _table_exists,
)
from ocint.state.service import StateService
from pydantic import BaseModel, ConfigDict


@dataclass(frozen=True)
class SummarySnapshot:
    sessions: int
    llm_steps: int
    cost: float
    tokens_input: int
    tokens_output: int
    tokens_reasoning: int
    tokens_cache_read: int
    tokens_cache_write: int
    tokens_total: int

    def as_dict(self) -> dict[str, int | float]:
        return {
            "sessions": self.sessions,
            "llm_steps": self.llm_steps,
            "cost": self.cost,
            "tokens_input": self.tokens_input,
            "tokens_output": self.tokens_output,
            "tokens_reasoning": self.tokens_reasoning,
            "tokens_cache_read": self.tokens_cache_read,
            "tokens_cache_write": self.tokens_cache_write,
            "tokens_total": self.tokens_total,
        }


@dataclass(frozen=True)
class CandidateOutput:
    summary: SummarySnapshot
    details: dict[str, int | float | str] = field(default_factory=dict)


@dataclass(frozen=True)
class Candidate:
    name: str
    hypothesis: str
    run: Callable[[Path, UsageWindow], CandidateOutput]


@dataclass(frozen=True)
class CandidateMeasurement:
    name: str
    hypothesis: str
    correct: bool
    timings: tuple[float, ...]
    speedup: float
    summary: SummarySnapshot
    diffs: tuple[str, ...]
    details: dict[str, int | float | str]

    @property
    def median_seconds(self) -> float:
        return statistics.median(self.timings)

    @property
    def min_seconds(self) -> float:
        return min(self.timings)

    @property
    def max_seconds(self) -> float:
        return max(self.timings)


@dataclass(frozen=True)
class ProjectionQuery:
    sql: str
    params: tuple[int | str, ...]


class ProjectedUsageRow(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    session_id: str | None = None
    time_created: int
    cost: float
    tokens_input: int
    tokens_output: int
    tokens_reasoning: int
    tokens_cache_read: int
    tokens_cache_write: int
    tokens_total: int | None = None


@dataclass
class SummaryAccumulator:
    sessions: set[str] = field(default_factory=set)
    llm_steps: int = 0
    cost: float = 0.0
    tokens_input: int = 0
    tokens_output: int = 0
    tokens_reasoning: int = 0
    tokens_cache_read: int = 0
    tokens_cache_write: int = 0
    tokens_total: int = 0

    def add(
        self,
        *,
        session_id: str | None,
        cost: float,
        tokens_input: int,
        tokens_output: int,
        tokens_reasoning: int,
        tokens_cache_read: int,
        tokens_cache_write: int,
        tokens_total: int | None,
    ) -> None:
        if session_id:
            self.sessions.add(session_id)
        self.llm_steps += 1
        self.cost += cost
        self.tokens_input += tokens_input
        self.tokens_output += tokens_output
        self.tokens_reasoning += tokens_reasoning
        self.tokens_cache_read += tokens_cache_read
        self.tokens_cache_write += tokens_cache_write
        if tokens_total is None:
            self.tokens_total += (
                tokens_input + tokens_output + tokens_reasoning + tokens_cache_read + tokens_cache_write
            )
        else:
            self.tokens_total += tokens_total

    def snapshot(self) -> SummarySnapshot:
        return SummarySnapshot(
            sessions=len(self.sessions),
            llm_steps=self.llm_steps,
            cost=self.cost,
            tokens_input=self.tokens_input,
            tokens_output=self.tokens_output,
            tokens_reasoning=self.tokens_reasoning,
            tokens_cache_read=self.tokens_cache_read,
            tokens_cache_write=self.tokens_cache_write,
            tokens_total=self.tokens_total,
        )


def main() -> None:
    args = _parse_args()
    source_db_path = args.db.expanduser()
    window = make_window(days=args.days, since=args.since, until=args.until)
    candidates = _candidates()
    candidates = _selected_candidates(candidates, args.candidate)

    with _benchmark_db_path(source_db_path, snapshot=not args.live) as benchmark_db_path:
        baseline_output = _baseline_current(benchmark_db_path, window)
        row_counts = _row_counts(benchmark_db_path, window)
        measurements = _measure_candidates(
            candidates,
            db_path=benchmark_db_path,
            window=window,
            expected=baseline_output.summary,
            repeat=args.repeat,
            warmup=args.warmup,
        )

        if args.format == "json":
            print(
                json.dumps(
                    _json_report(
                        source_db_path,
                        benchmark_db_path,
                        window,
                        row_counts,
                        baseline_output.summary,
                        measurements,
                    ),
                    indent=2,
                    sort_keys=True,
                )
            )
        else:
            _print_text_report(
                source_db_path,
                benchmark_db_path,
                window,
                row_counts,
                baseline_output.summary,
                measurements,
            )

        if args.profile_top > 0:
            _print_profiles(benchmark_db_path, window, candidates, measurements, args.profile_top)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Profile ocint state summary candidates against an OpenCode DB.")
    parser.add_argument("--db", required=True, type=Path, help="OpenCode SQLite DB path.")
    parser.add_argument("--days", type=int, default=2, help="Include this many UTC days when --since is omitted.")
    parser.add_argument("--since", help="UTC start date (YYYY-MM-DD).")
    parser.add_argument("--until", help="Inclusive UTC end date (YYYY-MM-DD).")
    parser.add_argument("--repeat", type=int, default=3, help="Measured runs per candidate.")
    parser.add_argument("--warmup", type=int, default=0, help="Unmeasured warmup runs per candidate.")
    parser.add_argument(
        "--profile-top", type=int, default=20, help="Print cProfile top cumulative functions for baseline and winner."
    )
    parser.add_argument("--format", choices=["table", "json"], default="table", help="Output format.")
    parser.add_argument(
        "--live",
        action="store_true",
        help="Benchmark the source DB directly instead of a stable read-only snapshot.",
    )
    parser.add_argument(
        "--candidate",
        action="append",
        help="Candidate name to benchmark. May be repeated. Defaults to all candidates.",
    )
    args = parser.parse_args()
    if args.repeat <= 0:
        parser.error("--repeat must be greater than zero")
    if args.warmup < 0:
        parser.error("--warmup must not be negative")
    return args


def _selected_candidates(candidates: Sequence[Candidate], selected: list[str] | None) -> list[Candidate]:
    if not selected:
        return list(candidates)
    candidate_by_name = {candidate.name: candidate for candidate in candidates}
    unknown = sorted(set(selected) - set(candidate_by_name))
    if unknown:
        names = ", ".join(candidate_by_name)
        raise SystemExit(f"unknown candidate(s): {', '.join(unknown)}; available: {names}")
    return [candidate_by_name[name] for name in selected]


@contextmanager
def _benchmark_db_path(source_db_path: Path, *, snapshot: bool) -> Iterator[Path]:
    if not snapshot:
        yield source_db_path
        return
    with TemporaryDirectory(prefix="ocint-state-summary-") as directory:
        snapshot_path = Path(directory) / "opencode-snapshot"
        with (
            closing(open_readonly_connection(source_db_path)) as source_connection,
            sqlite3.connect(snapshot_path) as snapshot_connection,
        ):
            source_connection.backup(snapshot_connection)
        yield snapshot_path


def _candidates() -> list[Candidate]:
    return [
        Candidate(
            name="baseline_current_python_filter",
            hypothesis="Current implementation: fetch and parse all part rows, then filter in Python.",
            run=_baseline_current,
        ),
        Candidate(
            name="h1_sql_filter_models_fetchall",
            hypothesis="Push time/type filtering into SQLite but keep fetchall plus current Pydantic row models.",
            run=_h1_sql_filter_models_fetchall,
        ),
        Candidate(
            name="h2_sql_filter_models_stream",
            hypothesis="Push time/type filtering into SQLite and stream current Pydantic row models.",
            run=_h2_sql_filter_models_stream,
        ),
        Candidate(
            name="h3_sql_projection_pydantic",
            hypothesis="Project only needed JSON fields in SQLite, validate each projected row with Pydantic, then aggregate in Python.",
            run=_h3_sql_projection_pydantic,
        ),
        Candidate(
            name="h3_sql_projection_no_pydantic",
            hypothesis="Project only needed JSON fields in SQLite, then aggregate sqlite rows directly in Python.",
            run=_h3_sql_projection_no_pydantic,
        ),
        Candidate(
            name="h4_single_sql_aggregate",
            hypothesis="Compute the whole summary in one SQLite aggregate query.",
            run=_h4_single_sql_aggregate,
        ),
        Candidate(
            name="h5_in_memory_usage_index",
            hypothesis="Build a normalized usage index in memory, then query summary from the index.",
            run=_h5_in_memory_usage_index,
        ),
    ]


def _measure_candidates(
    candidates: Sequence[Candidate],
    *,
    db_path: Path,
    window: UsageWindow,
    expected: SummarySnapshot,
    repeat: int,
    warmup: int,
) -> list[CandidateMeasurement]:
    results: list[CandidateMeasurement] = []
    baseline_median: float | None = None
    for candidate in candidates:
        for _ in range(warmup):
            candidate.run(db_path, window)

        timings: list[float] = []
        latest_output: CandidateOutput | None = None
        for _ in range(repeat):
            started = time.perf_counter()
            latest_output = candidate.run(db_path, window)
            timings.append(time.perf_counter() - started)

        if latest_output is None:
            raise RuntimeError(f"candidate did not run: {candidate.name}")

        diffs = tuple(_summary_diffs(expected, latest_output.summary))
        median = statistics.median(timings)
        if candidate.name == "baseline_current_python_filter":
            baseline_median = median
        speedup = 1.0 if baseline_median in (None, 0.0) else baseline_median / median
        results.append(
            CandidateMeasurement(
                name=candidate.name,
                hypothesis=candidate.hypothesis,
                correct=not diffs,
                timings=tuple(timings),
                speedup=speedup,
                summary=latest_output.summary,
                diffs=diffs,
                details=latest_output.details,
            )
        )
    return results


def _baseline_current(db_path: Path, window: UsageWindow) -> CandidateOutput:
    summary = StateService(OpenCodeRepository(db_path)).summary(window)
    return CandidateOutput(
        SummarySnapshot(
            sessions=summary.sessions,
            llm_steps=summary.llm_steps,
            cost=summary.cost,
            tokens_input=summary.tokens.input,
            tokens_output=summary.tokens.output,
            tokens_reasoning=summary.tokens.reasoning,
            tokens_cache_read=summary.tokens.cache_read,
            tokens_cache_write=summary.tokens.cache_write,
            tokens_total=summary.tokens.total,
        )
    )


def _h1_sql_filter_models_fetchall(db_path: Path, window: UsageWindow) -> CandidateOutput:
    with closing(open_readonly_connection(db_path)) as connection:
        query = _filtered_part_model_query(connection, window)
        rows = connection.execute(query.sql, query.params).fetchall()
        session_by_message = _session_message_map(connection)
        parts = [_part_from_row(row, session_by_message=session_by_message) for row in rows]
    return CandidateOutput(_summary_from_parts(parts), {"matched_rows": len(parts)})


def _h2_sql_filter_models_stream(db_path: Path, window: UsageWindow) -> CandidateOutput:
    accumulator = SummaryAccumulator()
    matched_rows = 0
    with closing(open_readonly_connection(db_path)) as connection:
        query = _filtered_part_model_query(connection, window)
        session_by_message = _session_message_map(connection)
        for row in connection.execute(query.sql, query.params):
            part = _part_from_row(row, session_by_message=session_by_message)
            _add_part(accumulator, part)
            matched_rows += 1
    return CandidateOutput(accumulator.snapshot(), {"matched_rows": matched_rows})


def _h3_sql_projection_pydantic(db_path: Path, window: UsageWindow) -> CandidateOutput:
    accumulator = SummaryAccumulator()
    matched_rows = 0
    with closing(open_readonly_connection(db_path)) as connection:
        query = _projected_usage_query(connection, window, schema_name=None)
        for row in connection.execute(query.sql, query.params):
            usage = ProjectedUsageRow.model_validate(dict(row))
            _add_projected_model(accumulator, usage)
            matched_rows += 1
    return CandidateOutput(accumulator.snapshot(), {"matched_rows": matched_rows, "row_model": "pydantic"})


def _h3_sql_projection_no_pydantic(db_path: Path, window: UsageWindow) -> CandidateOutput:
    accumulator = SummaryAccumulator()
    matched_rows = 0
    with closing(open_readonly_connection(db_path)) as connection:
        query = _projected_usage_query(connection, window, schema_name=None)
        for row in connection.execute(query.sql, query.params):
            _add_projected_row(accumulator, row)
            matched_rows += 1
    return CandidateOutput(accumulator.snapshot(), {"matched_rows": matched_rows, "row_model": "none"})


def _h4_single_sql_aggregate(db_path: Path, window: UsageWindow) -> CandidateOutput:
    with closing(open_readonly_connection(db_path)) as connection:
        query = _aggregate_usage_query(connection, window, schema_name=None, source_query=None)
        row = connection.execute(query.sql, query.params).fetchone()
    if row is None:
        raise RuntimeError("aggregate query returned no row")
    return CandidateOutput(_snapshot_from_aggregate_row(row))


def _h5_in_memory_usage_index(db_path: Path, window: UsageWindow) -> CandidateOutput:
    source_uri = f"{db_path.resolve().as_uri()}?mode=ro"
    with closing(open_readonly_connection(db_path)) as source_connection:
        projection = _projected_usage_query(source_connection, None, schema_name="opencode")

    with sqlite3.connect(":memory:", uri=True) as index_connection:
        index_connection.row_factory = sqlite3.Row
        index_connection.execute("ATTACH DATABASE ? AS opencode", (source_uri,))
        index_connection.executescript(
            """
            CREATE TABLE usage_index (
              session_id TEXT,
              time_created INTEGER NOT NULL,
              cost REAL NOT NULL,
              tokens_input INTEGER NOT NULL,
              tokens_output INTEGER NOT NULL,
              tokens_reasoning INTEGER NOT NULL,
              tokens_cache_read INTEGER NOT NULL,
              tokens_cache_write INTEGER NOT NULL,
              tokens_total INTEGER
            );
            CREATE INDEX usage_index_time_created ON usage_index(time_created);
            """
        )
        started_build = time.perf_counter()
        index_connection.execute(
            """
            INSERT INTO usage_index (
              session_id,
              time_created,
              cost,
              tokens_input,
              tokens_output,
              tokens_reasoning,
              tokens_cache_read,
              tokens_cache_write,
              tokens_total
            )
            """
            + projection.sql,
            projection.params,
        )
        index_connection.commit()
        build_seconds = time.perf_counter() - started_build
        index_rows = int(index_connection.execute("SELECT COUNT(*) FROM usage_index").fetchone()[0] or 0)

        source_query = _usage_index_window_query(window)
        aggregate = _aggregate_usage_query(index_connection, window, schema_name=None, source_query=source_query.sql)
        started_query = time.perf_counter()
        row = index_connection.execute(aggregate.sql, source_query.params + aggregate.params).fetchone()
        query_seconds = time.perf_counter() - started_query
    if row is None:
        raise RuntimeError("index aggregate query returned no row")
    return CandidateOutput(
        _snapshot_from_aggregate_row(row),
        {
            "index_rows": index_rows,
            "index_build_seconds": build_seconds,
            "index_query_seconds": query_seconds,
        },
    )


def _filtered_part_model_query(connection: sqlite3.Connection, window: UsageWindow) -> ProjectionQuery:
    if not _table_exists(connection, "part"):
        return ProjectionQuery("SELECT NULL AS id WHERE 0", ())
    columns = _columns(connection, "part")
    data = opencode_schema.data_expr(columns)
    time_expr = opencode_schema.column_expr(columns, ["time_created", "timeCreated", "created_at", "createdAt"])
    where, params = _usage_where(data, time_expr, window)
    return ProjectionQuery(
        f"""
        SELECT
          {opencode_schema.column_select(columns, ["id"], "id")},
          {opencode_schema.column_select(columns, ["message_id", "messageID"], "message_id")},
          {opencode_schema.column_select(columns, ["session_id", "sessionID"], "session_id")},
          {opencode_schema.column_select(columns, ["time_created", "timeCreated", "created_at", "createdAt"], "time_created")},
          {opencode_schema.column_select(columns, ["time_updated", "timeUpdated", "updated_at", "updatedAt"], "time_updated")},
          {data} AS {_quote("data")}
        FROM {_quote("part")}
        {where}
        """,
        tuple(params),
    )


def _projected_usage_query(
    connection: sqlite3.Connection, window: UsageWindow | None, *, schema_name: str | None
) -> ProjectionQuery:
    if not _table_exists(connection, "part"):
        return ProjectionQuery(
            """
            SELECT NULL AS session_id, NULL AS time_created, 0.0 AS cost,
                   0 AS tokens_input, 0 AS tokens_output, 0 AS tokens_reasoning,
                   0 AS tokens_cache_read, 0 AS tokens_cache_write, NULL AS tokens_total
            WHERE 0
            """,
            (),
        )
    columns = _columns(connection, "part")
    data = opencode_schema.data_expr(columns, table_alias="p")
    time_expr = opencode_schema.column_expr(
        columns, ["time_created", "timeCreated", "created_at", "createdAt"], table_alias="p"
    )
    message_expr = opencode_schema.column_expr(columns, ["message_id", "messageID"], table_alias="p")
    part_session_expr = opencode_schema.column_expr(columns, ["session_id", "sessionID"], table_alias="p")
    session_join, session_message_expr = _session_message_join(connection, schema_name, message_expr)
    resolved_session_expr = f"NULLIF(COALESCE(CAST({part_session_expr} AS TEXT), {session_message_expr}), '')"
    where, params = _usage_where(data, time_expr, window)
    return ProjectionQuery(
        f"""
        SELECT
          {resolved_session_expr} AS session_id,
          CAST({time_expr} AS INTEGER) AS time_created,
          COALESCE(CAST({opencode_schema.json_extract(data, "$.cost")} AS REAL), 0.0) AS cost,
          COALESCE(CAST({opencode_schema.json_extract(data, "$.tokens.input")} AS INTEGER), 0) AS tokens_input,
          COALESCE(CAST({opencode_schema.json_extract(data, "$.tokens.output")} AS INTEGER), 0) AS tokens_output,
          COALESCE(CAST({opencode_schema.json_extract(data, "$.tokens.reasoning")} AS INTEGER), 0) AS tokens_reasoning,
          COALESCE(CAST({opencode_schema.json_extract(data, "$.tokens.cache.read")} AS INTEGER), 0) AS tokens_cache_read,
          COALESCE(CAST({opencode_schema.json_extract(data, "$.tokens.cache.write")} AS INTEGER), 0) AS tokens_cache_write,
          CAST({opencode_schema.json_extract(data, "$.tokens.total")} AS INTEGER) AS tokens_total
        FROM {_table_ref(schema_name, "part")} AS {_quote("p")}
        {session_join}
        {where}
        """,
        tuple(params),
    )


def _aggregate_usage_query(
    connection: sqlite3.Connection,
    window: UsageWindow,
    *,
    schema_name: str | None,
    source_query: str | None,
) -> ProjectionQuery:
    if source_query is None:
        projection = _projected_usage_query(connection, window, schema_name=schema_name)
        params = projection.params
        source_sql = projection.sql
    else:
        source_sql = source_query
        params = ()
    return ProjectionQuery(
        f"""
        WITH usage AS (
          {source_sql}
        )
        SELECT
          COUNT(*) AS llm_steps,
          COUNT(DISTINCT session_id) AS sessions,
          COALESCE(SUM(cost), 0.0) AS cost,
          COALESCE(SUM(tokens_input), 0) AS tokens_input,
          COALESCE(SUM(tokens_output), 0) AS tokens_output,
          COALESCE(SUM(tokens_reasoning), 0) AS tokens_reasoning,
          COALESCE(SUM(tokens_cache_read), 0) AS tokens_cache_read,
          COALESCE(SUM(tokens_cache_write), 0) AS tokens_cache_write,
          COALESCE(SUM(COALESCE(
            tokens_total,
            tokens_input + tokens_output + tokens_reasoning + tokens_cache_read + tokens_cache_write
          )), 0) AS tokens_total
        FROM usage
        """,
        tuple(params),
    )


def _usage_index_window_query(window: UsageWindow) -> ProjectionQuery:
    where: list[str] = ["time_created IS NOT NULL"]
    params: list[int] = []
    if window.start_ms is not None:
        where.append("time_created >= ?")
        params.append(window.start_ms)
    if window.end_ms is not None:
        where.append("time_created < ?")
        params.append(window.end_ms)
    return ProjectionQuery("SELECT * FROM usage_index WHERE " + " AND ".join(where), tuple(params))


def _usage_where(data: str, time_expr: str, window: UsageWindow | None) -> tuple[str, list[int | str]]:
    where = [
        f"{time_expr} IS NOT NULL",
        f"{opencode_schema.json_extract(data, '$.type')} = ?",
    ]
    params: list[int | str] = ["step-finish"]
    if window is not None and window.start_ms is not None:
        where.append(f"CAST({time_expr} AS INTEGER) >= ?")
        params.append(window.start_ms)
    if window is not None and window.end_ms is not None:
        where.append(f"CAST({time_expr} AS INTEGER) < ?")
        params.append(window.end_ms)
    return "WHERE " + " AND ".join(where), params


def _session_message_join(
    connection: sqlite3.Connection, schema_name: str | None, message_expr: str
) -> tuple[str, str]:
    if not _table_exists(connection, "session_message"):
        return "", "NULL"
    columns = _columns(connection, "session_message")
    session_col = opencode_schema.first_column(columns, ["session_id", "sessionID"])
    message_col = opencode_schema.first_column(columns, ["message_id", "messageID"])
    if session_col is None or message_col is None:
        return "", "NULL"
    join = (
        f"LEFT JOIN {_table_ref(schema_name, 'session_message')} AS {_quote('sm')} "
        f"ON NULLIF(CAST({message_expr} AS TEXT), '') = CAST({_quote('sm')}.{_quote(message_col)} AS TEXT)"
    )
    return join, f"CAST({_quote('sm')}.{_quote(session_col)} AS TEXT)"


def _table_ref(schema_name: str | None, table: str) -> str:
    if schema_name is None:
        return _quote(table)
    return f"{_quote(schema_name)}.{_quote(table)}"


def _part_from_row(row: sqlite3.Row, *, session_by_message: dict[str, str]) -> OpenCodePartRow:
    message_id = _optional_str(row["message_id"])
    session_id = _optional_str(row["session_id"]) or (session_by_message.get(message_id) if message_id else None)
    return OpenCodePartRow(
        id=str(row["id"]),
        message_id=message_id,
        session_id=session_id,
        time_created=_optional_int(row["time_created"]),
        time_updated=_optional_int(row["time_updated"]),
        data=_parse_payload(OpenCodePartData, row["data"]),
    )


def _summary_from_parts(parts: Sequence[OpenCodePartRow]) -> SummarySnapshot:
    accumulator = SummaryAccumulator()
    for part in parts:
        _add_part(accumulator, part)
    return accumulator.snapshot()


def _add_part(accumulator: SummaryAccumulator, part: OpenCodePartRow) -> None:
    accumulator.add(
        session_id=part.session_id,
        cost=float(part.data.cost or 0.0),
        tokens_input=part.data.tokens.input,
        tokens_output=part.data.tokens.output,
        tokens_reasoning=part.data.tokens.reasoning,
        tokens_cache_read=part.data.tokens.cache.read,
        tokens_cache_write=part.data.tokens.cache.write,
        tokens_total=part.data.tokens.total,
    )


def _add_projected_row(accumulator: SummaryAccumulator, row: sqlite3.Row) -> None:
    accumulator.add(
        session_id=_optional_str(row["session_id"]),
        cost=_float_value(row["cost"]),
        tokens_input=_int_value(row["tokens_input"]),
        tokens_output=_int_value(row["tokens_output"]),
        tokens_reasoning=_int_value(row["tokens_reasoning"]),
        tokens_cache_read=_int_value(row["tokens_cache_read"]),
        tokens_cache_write=_int_value(row["tokens_cache_write"]),
        tokens_total=_optional_int(row["tokens_total"]),
    )


def _add_projected_model(accumulator: SummaryAccumulator, row: ProjectedUsageRow) -> None:
    accumulator.add(
        session_id=row.session_id,
        cost=row.cost,
        tokens_input=row.tokens_input,
        tokens_output=row.tokens_output,
        tokens_reasoning=row.tokens_reasoning,
        tokens_cache_read=row.tokens_cache_read,
        tokens_cache_write=row.tokens_cache_write,
        tokens_total=row.tokens_total,
    )


def _snapshot_from_aggregate_row(row: sqlite3.Row) -> SummarySnapshot:
    return SummarySnapshot(
        sessions=_int_value(row["sessions"]),
        llm_steps=_int_value(row["llm_steps"]),
        cost=_float_value(row["cost"]),
        tokens_input=_int_value(row["tokens_input"]),
        tokens_output=_int_value(row["tokens_output"]),
        tokens_reasoning=_int_value(row["tokens_reasoning"]),
        tokens_cache_read=_int_value(row["tokens_cache_read"]),
        tokens_cache_write=_int_value(row["tokens_cache_write"]),
        tokens_total=_int_value(row["tokens_total"]),
    )


def _int_value(value: Any) -> int:
    if value is None or value == "":
        return 0
    return int(value)


def _float_value(value: Any) -> float:
    if value is None or value == "":
        return 0.0
    return float(value)


def _summary_diffs(expected: SummarySnapshot, actual: SummarySnapshot) -> list[str]:
    diffs: list[str] = []
    expected_values = expected.as_dict()
    actual_values = actual.as_dict()
    for key, expected_value in expected_values.items():
        actual_value = actual_values[key]
        if key == "cost":
            if abs(float(expected_value) - float(actual_value)) > 0.000001:
                diffs.append(f"{key}: expected {expected_value}, got {actual_value}")
        elif expected_value != actual_value:
            diffs.append(f"{key}: expected {expected_value}, got {actual_value}")
    return diffs


def _row_counts(db_path: Path, window: UsageWindow) -> dict[str, int]:
    with closing(open_readonly_connection(db_path)) as connection:
        if not _table_exists(connection, "part"):
            return {"part_rows": 0, "step_finish_rows": 0, "window_step_finish_rows": 0}
        part_rows = int(connection.execute(f"SELECT COUNT(*) FROM {_quote('part')}").fetchone()[0] or 0)
        all_step_finish = _count_projected_usage(connection, None)
        window_step_finish = _count_projected_usage(connection, window)
    return {
        "part_rows": part_rows,
        "step_finish_rows": all_step_finish,
        "window_step_finish_rows": window_step_finish,
    }


def _count_projected_usage(connection: sqlite3.Connection, window: UsageWindow | None) -> int:
    query = _projected_usage_query(connection, window, schema_name=None)
    row = connection.execute(f"SELECT COUNT(*) FROM ({query.sql})", query.params).fetchone()
    return int(row[0] or 0)


def _json_report(
    source_db_path: Path,
    benchmark_db_path: Path,
    window: UsageWindow,
    row_counts: dict[str, int],
    baseline: SummarySnapshot,
    measurements: Sequence[CandidateMeasurement],
) -> dict[str, Any]:
    return {
        "source_db": str(source_db_path),
        "benchmark_db": str(benchmark_db_path),
        "window": window.label,
        "row_counts": row_counts,
        "baseline_summary": baseline.as_dict(),
        "winner": _winner(measurements).name,
        "candidates": [
            {
                "name": measurement.name,
                "hypothesis": measurement.hypothesis,
                "correct": measurement.correct,
                "median_seconds": measurement.median_seconds,
                "min_seconds": measurement.min_seconds,
                "max_seconds": measurement.max_seconds,
                "speedup": measurement.speedup,
                "timings": list(measurement.timings),
                "diffs": list(measurement.diffs),
                "details": measurement.details,
                "summary": measurement.summary.as_dict(),
            }
            for measurement in measurements
        ],
    }


def _print_text_report(
    source_db_path: Path,
    benchmark_db_path: Path,
    window: UsageWindow,
    row_counts: dict[str, int],
    baseline: SummarySnapshot,
    measurements: Sequence[CandidateMeasurement],
) -> None:
    print(f"SOURCE_DB: {source_db_path}")
    print(f"BENCHMARK_DB: {benchmark_db_path}")
    print(f"WINDOW: {window.label}")
    print("ROW_COUNTS:")
    for key, value in row_counts.items():
        print(f"  {key}: {value:,}")
    print("BASELINE_SUMMARY:")
    for key, value in baseline.as_dict().items():
        print(f"  {key}: {value}")
    print()
    print(_measurements_table(measurements))
    winner = _winner(measurements)
    print()
    print(f"WINNER: {winner.name}")
    print(f"WINNER_MEDIAN_SECONDS: {winner.median_seconds:.6f}")
    print(f"WINNER_SPEEDUP: {winner.speedup:.2f}x")
    if winner.details:
        print("WINNER_DETAILS:")
        for key, value in winner.details.items():
            print(f"  {key}: {value}")
    incorrect = [measurement for measurement in measurements if not measurement.correct]
    if incorrect:
        print("INCORRECT_CANDIDATES:")
        for measurement in incorrect:
            print(f"  {measurement.name}: {'; '.join(measurement.diffs)}")


def _measurements_table(measurements: Sequence[CandidateMeasurement]) -> str:
    rows = [
        [
            "candidate",
            "ok",
            "median_s",
            "min_s",
            "max_s",
            "speedup",
            "notes",
        ]
    ]
    for measurement in measurements:
        rows.append(
            [
                measurement.name,
                "yes" if measurement.correct else "no",
                f"{measurement.median_seconds:.6f}",
                f"{measurement.min_seconds:.6f}",
                f"{measurement.max_seconds:.6f}",
                f"{measurement.speedup:.2f}x",
                _details_note(measurement.details),
            ]
        )
    widths = [max(len(row[index]) for row in rows) for index in range(len(rows[0]))]
    lines = []
    for row_index, row in enumerate(rows):
        lines.append("  ".join(cell.ljust(widths[index]) for index, cell in enumerate(row)))
        if row_index == 0:
            lines.append("  ".join("-" * width for width in widths))
    return "\n".join(lines)


def _details_note(details: dict[str, int | float | str]) -> str:
    if not details:
        return ""
    return ", ".join(f"{key}={value}" for key, value in details.items())


def _winner(measurements: Sequence[CandidateMeasurement]) -> CandidateMeasurement:
    correct = [measurement for measurement in measurements if measurement.correct]
    if not correct:
        raise RuntimeError("no correct candidates")
    return min(correct, key=lambda measurement: measurement.median_seconds)


def _print_profiles(
    db_path: Path,
    window: UsageWindow,
    candidates: Sequence[Candidate],
    measurements: Sequence[CandidateMeasurement],
    top: int,
) -> None:
    candidate_by_name = {candidate.name: candidate for candidate in candidates}
    baseline = candidate_by_name["baseline_current_python_filter"]
    winner = candidate_by_name[_winner(measurements).name]
    print()
    print(f"CPROFILE baseline ({baseline.name})")
    print(_profile_candidate(baseline, db_path, window, top))
    if winner.name != baseline.name:
        print()
        print(f"CPROFILE winner ({winner.name})")
        print(_profile_candidate(winner, db_path, window, top))


def _profile_candidate(candidate: Candidate, db_path: Path, window: UsageWindow, top: int) -> str:
    profile = cProfile.Profile()
    profile.enable()
    candidate.run(db_path, window)
    profile.disable()
    stream = io.StringIO()
    pstats.Stats(profile, stream=stream).strip_dirs().sort_stats("cumtime").print_stats(top)
    return stream.getvalue()


if __name__ == "__main__":
    main()
