from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

from sqlalchemy import delete, func, insert, select, text, tuple_, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from ocint.ctx.db.schema import ctx_event, ctx_file_touched, ctx_session, ctx_source


class CtxImportRepository:
    def __init__(self, session: Session, *, db_path: Path) -> None:
        self._session = session
        self.db_path = db_path

    def upsert_source(
        self,
        *,
        provider: str,
        source_type: str,
        name: str,
        source_path: str,
    ) -> int:
        values = {
            "provider": provider,
            "source_type": source_type,
            "name": name,
            "source_path": source_path,
            "sessions": 0,
            "events": 0,
        }
        statement = sqlite_insert(ctx_source).values(values)
        self._session.execute(
            statement.on_conflict_do_update(
                index_elements=[ctx_source.c.provider, ctx_source.c.source_type, ctx_source.c.source_path],
                set_={"name": name},
            )
        )
        source_id = self._session.execute(
            select(ctx_source.c.id).where(
                ctx_source.c.provider == provider,
                ctx_source.c.source_type == source_type,
                ctx_source.c.source_path == source_path,
            )
        ).scalar_one()
        return int(source_id)

    def update_source_counts(self, *, source_id: int, sessions: int, events: int) -> None:
        self._session.execute(
            update(ctx_source).where(ctx_source.c.id == source_id).values(sessions=sessions, events=events)
        )

    def session_reconciliation_state(self, source_id: int) -> dict[str, str]:
        rows = self._session.execute(
            select(ctx_session.c.provider_session_id, ctx_session.c.source_fingerprint).where(
                ctx_session.c.source_id == source_id
            )
        ).mappings()
        return {str(row["provider_session_id"]): str(row["source_fingerprint"] or "") for row in rows}

    def event_reconciliation_state(self, source_id: int) -> dict[tuple[str, str], dict[str, str | None]]:
        rows = self._session.execute(
            select(
                ctx_event.c.source_table,
                ctx_event.c.event_id,
                ctx_event.c.source_fingerprint,
                ctx_event.c.provider_session_id,
                ctx_event.c.message_id,
            ).where(ctx_event.c.source_id == source_id)
        ).mappings()
        return {
            (str(row["source_table"]), str(row["event_id"])): {
                "source_fingerprint": str(row["source_fingerprint"] or ""),
                "provider_session_id": _optional_str(row["provider_session_id"]),
                "message_id": _optional_str(row["message_id"]),
            }
            for row in rows
        }

    def upsert_sessions(self, sessions: Iterable[Mapping[str, Any]]) -> int:
        rows = [dict(values) for values in sessions]
        if not rows:
            return 0
        statement = sqlite_insert(ctx_session)
        update_columns = [
            column.name
            for column in ctx_session.columns
            if column.name not in {"id", "source_id", "provider_session_id"}
        ]
        self._session.execute(
            statement.on_conflict_do_update(
                index_elements=[ctx_session.c.source_id, ctx_session.c.provider_session_id],
                set_={column: getattr(statement.excluded, column) for column in update_columns},
            ),
            rows,
        )
        return len(rows)

    def insert_sessions(self, sessions: Iterable[Mapping[str, Any]]) -> int:
        rows = [dict(values) for values in sessions]
        if not rows:
            return 0
        self._session.execute(sqlite_insert(ctx_session), rows)
        return len(rows)

    def upsert_events_with_files(
        self,
        event_rows: Iterable[tuple[Mapping[str, Any], Iterable[str]]],
    ) -> tuple[int, int]:
        pairs = [(dict(values), list(paths)) for values, paths in event_rows]
        rows = [values for values, _paths in pairs]
        if not rows:
            return 0, 0

        statement = sqlite_insert(ctx_event)
        update_columns = [
            column.name
            for column in ctx_event.columns
            if column.name not in {"id", "source_id", "source_table", "event_id"}
        ]
        self._session.execute(
            statement.on_conflict_do_update(
                index_elements=[ctx_event.c.source_id, ctx_event.c.source_table, ctx_event.c.event_id],
                set_={column: getattr(statement.excluded, column) for column in update_columns},
            ),
            rows,
        )
        event_pk_by_key = self._event_primary_keys(rows)
        self._replace_fts_rows(rows, event_pk_by_key)
        files_written = self._replace_file_rows(pairs)
        return len(rows), files_written

    def insert_events_with_files(
        self,
        event_rows: Iterable[tuple[Mapping[str, Any], Iterable[str]]],
    ) -> tuple[int, int]:
        pairs = [(dict(values), list(paths)) for values, paths in event_rows]
        rows = [values for values, _paths in pairs]
        if not rows:
            return 0, 0
        self._session.execute(sqlite_insert(ctx_event), rows)
        event_pk_by_key = self._event_primary_keys(rows)
        self._replace_fts_rows(rows, event_pk_by_key)
        files_written = self._insert_file_rows(pairs)
        return len(rows), files_written

    def prune_events_not_seen(self, *, source_id: int, seen_keys: Sequence[tuple[str, str]]) -> int:
        self._replace_seen_event_keys_temp_table(seen_keys)
        self._session.execute(
            text(
                """
                DELETE FROM ctx_event_fts
                WHERE event_pk IN (
                    SELECT e.id
                    FROM ctx_event AS e
                    WHERE e.source_id = :source_id
                      AND NOT EXISTS (
                          SELECT 1
                          FROM temp_ctx_seen_event_keys AS seen
                          WHERE seen.source_table = e.source_table
                            AND seen.event_id = e.event_id
                      )
                )
                """
            ),
            {"source_id": source_id},
        )
        self._session.execute(
            text(
                """
                DELETE FROM ctx_file_touched
                WHERE source_id = :source_id
                  AND NOT EXISTS (
                      SELECT 1
                      FROM temp_ctx_seen_event_keys AS seen
                      WHERE seen.source_table = ctx_file_touched.source_table
                        AND seen.event_id = ctx_file_touched.event_id
                  )
                """
            ),
            {"source_id": source_id},
        )
        pruned = int(
            self._session.execute(
                text(
                    """
                    SELECT COUNT(*)
                    FROM ctx_event
                    WHERE source_id = :source_id
                      AND NOT EXISTS (
                          SELECT 1
                          FROM temp_ctx_seen_event_keys AS seen
                          WHERE seen.source_table = ctx_event.source_table
                            AND seen.event_id = ctx_event.event_id
                      )
                    """
                ),
                {"source_id": source_id},
            ).scalar_one()
            or 0
        )
        self._session.execute(
            text(
                """
                DELETE FROM ctx_event
                WHERE source_id = :source_id
                  AND NOT EXISTS (
                      SELECT 1
                      FROM temp_ctx_seen_event_keys AS seen
                      WHERE seen.source_table = ctx_event.source_table
                        AND seen.event_id = ctx_event.event_id
                  )
                """
            ),
            {"source_id": source_id},
        )
        return pruned

    def prune_sessions_not_seen(self, *, source_id: int, seen_session_ids: Sequence[str]) -> int:
        self._replace_seen_session_ids_temp_table(seen_session_ids)
        pruned = int(
            self._session.execute(
                text(
                    """
                    SELECT COUNT(*)
                    FROM ctx_session
                    WHERE source_id = :source_id
                      AND NOT EXISTS (
                          SELECT 1
                          FROM temp_ctx_seen_session_ids AS seen
                          WHERE seen.provider_session_id = ctx_session.provider_session_id
                      )
                    """
                ),
                {"source_id": source_id},
            ).scalar_one()
            or 0
        )
        self._session.execute(
            text(
                """
                DELETE FROM ctx_session
                WHERE source_id = :source_id
                  AND NOT EXISTS (
                      SELECT 1
                      FROM temp_ctx_seen_session_ids AS seen
                      WHERE seen.provider_session_id = ctx_session.provider_session_id
                  )
                """
            ),
            {"source_id": source_id},
        )
        return pruned

    def count_sessions(self, source_id: int) -> int:
        return int(
            self._session.execute(
                select(func.count()).select_from(ctx_session).where(ctx_session.c.source_id == source_id)
            ).scalar_one()
            or 0
        )

    def count_events(self, source_id: int) -> int:
        return int(
            self._session.execute(
                select(func.count()).select_from(ctx_event).where(ctx_event.c.source_id == source_id)
            ).scalar_one()
            or 0
        )

    def next_event_pk(self) -> int:
        return int(self._session.execute(select(func.coalesce(func.max(ctx_event.c.id), 0) + 1)).scalar_one())

    def _event_primary_keys(self, rows: Sequence[Mapping[str, Any]]) -> dict[tuple[int, str, str], int]:
        if all("id" in row for row in rows):
            return {_event_key(row): int(row["id"]) for row in rows}
        keys = list(dict.fromkeys(_event_key(row) for row in rows))
        statement = select(
            ctx_event.c.source_id,
            ctx_event.c.source_table,
            ctx_event.c.event_id,
            ctx_event.c.id,
        ).where(tuple_(ctx_event.c.source_id, ctx_event.c.source_table, ctx_event.c.event_id).in_(keys))
        found = {
            (int(row["source_id"]), str(row["source_table"]), str(row["event_id"])): int(row["id"])
            for row in self._session.execute(statement).mappings()
        }
        missing = [key for key in keys if key not in found]
        if missing:
            raise RuntimeError(f"ctx event primary key lookup missed upserted events: {missing[:3]}")
        return found

    def _replace_fts_rows(
        self,
        rows: Sequence[Mapping[str, Any]],
        event_pk_by_key: Mapping[tuple[int, str, str], int],
    ) -> None:
        event_pks = [event_pk_by_key[_event_key(row)] for row in rows]
        self._replace_affected_event_pks_temp_table(event_pks)
        self._session.execute(
            text(
                """
                DELETE FROM ctx_event_fts
                WHERE event_pk IN (SELECT event_pk FROM temp_ctx_affected_event_pks)
                """
            )
        )
        fts_rows = [
            {
                "search_text": row["search_text"],
                "event_pk": event_pk_by_key[_event_key(row)],
                "event_id": row["event_id"],
                "source_table": row["source_table"],
            }
            for row in rows
        ]
        self._session.execute(
            text(
                """
                INSERT INTO ctx_event_fts(search_text, event_pk, event_id, source_table)
                VALUES (:search_text, :event_pk, :event_id, :source_table)
                """
            ),
            fts_rows,
        )

    def _replace_file_rows(self, pairs: Sequence[tuple[Mapping[str, Any], list[str]]]) -> int:
        keys = list(dict.fromkeys(_event_key(values) for values, _paths in pairs))
        if keys:
            self._session.execute(
                delete(ctx_file_touched).where(
                    tuple_(
                        ctx_file_touched.c.source_id, ctx_file_touched.c.source_table, ctx_file_touched.c.event_id
                    ).in_(keys)
                )
            )
        file_rows = _file_rows(pairs)
        if not file_rows:
            return 0
        self._session.execute(insert(ctx_file_touched), file_rows)
        return len(file_rows)

    def _insert_file_rows(self, pairs: Sequence[tuple[Mapping[str, Any], list[str]]]) -> int:
        file_rows = _file_rows(pairs)
        if not file_rows:
            return 0
        self._session.execute(sqlite_insert(ctx_file_touched), file_rows)
        return len(file_rows)

    def _replace_seen_event_keys_temp_table(self, seen_keys: Sequence[tuple[str, str]]) -> None:
        self._session.execute(
            text(
                """
                CREATE TEMP TABLE IF NOT EXISTS temp_ctx_seen_event_keys(
                    source_table TEXT NOT NULL,
                    event_id TEXT NOT NULL,
                    PRIMARY KEY(source_table, event_id)
                )
                """
            )
        )
        self._session.execute(text("DELETE FROM temp_ctx_seen_event_keys"))
        rows = [{"source_table": source_table, "event_id": event_id} for source_table, event_id in seen_keys]
        if rows:
            self._session.execute(
                text(
                    """
                    INSERT OR IGNORE INTO temp_ctx_seen_event_keys(source_table, event_id)
                    VALUES (:source_table, :event_id)
                    """
                ),
                rows,
            )

    def _replace_seen_session_ids_temp_table(self, seen_session_ids: Sequence[str]) -> None:
        self._session.execute(
            text(
                """
                CREATE TEMP TABLE IF NOT EXISTS temp_ctx_seen_session_ids(
                    provider_session_id TEXT NOT NULL PRIMARY KEY
                )
                """
            )
        )
        self._session.execute(text("DELETE FROM temp_ctx_seen_session_ids"))
        rows = [{"provider_session_id": provider_session_id} for provider_session_id in seen_session_ids]
        if rows:
            self._session.execute(
                text(
                    """
                    INSERT OR IGNORE INTO temp_ctx_seen_session_ids(provider_session_id)
                    VALUES (:provider_session_id)
                    """
                ),
                rows,
            )

    def _replace_affected_event_pks_temp_table(self, event_pks: Sequence[int]) -> None:
        self._session.execute(
            text(
                """
                CREATE TEMP TABLE IF NOT EXISTS temp_ctx_affected_event_pks(
                    event_pk INTEGER NOT NULL PRIMARY KEY
                )
                """
            )
        )
        self._session.execute(text("DELETE FROM temp_ctx_affected_event_pks"))
        self._session.execute(
            text("INSERT OR IGNORE INTO temp_ctx_affected_event_pks(event_pk) VALUES (:event_pk)"),
            [{"event_pk": event_pk} for event_pk in event_pks],
        )


def _event_key(row: Mapping[str, Any]) -> tuple[int, str, str]:
    return (int(row["source_id"]), str(row["source_table"]), str(row["event_id"]))


def _file_rows(pairs: Sequence[tuple[Mapping[str, Any], list[str]]]) -> list[dict[str, Any]]:
    file_rows: list[dict[str, Any]] = []
    seen: set[tuple[int, str, str, str]] = set()
    for values, paths in pairs:
        for path in paths:
            if not path:
                continue
            key = (int(values["source_id"]), str(values["source_table"]), str(values["event_id"]), path)
            if key in seen:
                continue
            seen.add(key)
            file_rows.append(
                {
                    "source_id": values["source_id"],
                    "provider": values["provider"],
                    "path": path,
                    "provider_session_id": values["provider_session_id"],
                    "event_id": values["event_id"],
                    "source_table": values["source_table"],
                }
            )
    return file_rows


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    result = str(value)
    return result if result else None
