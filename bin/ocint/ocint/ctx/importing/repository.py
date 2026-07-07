from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

from sqlalchemy import delete, select, text, tuple_
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
        imported_at: int,
        sessions: int,
        events: int,
        checkpoint_payload: str | None,
    ) -> int:
        values = {
            "provider": provider,
            "source_type": source_type,
            "name": name,
            "source_path": source_path,
            "imported_at": imported_at,
            "sessions": sessions,
            "events": events,
            "checkpoint_payload": checkpoint_payload,
        }
        statement = sqlite_insert(ctx_source).values(values)
        self._session.execute(
            statement.on_conflict_do_update(
                index_elements=[ctx_source.c.provider, ctx_source.c.source_type, ctx_source.c.source_path],
                set_=values,
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

    def clear_source_rows(self, source_id: int) -> None:
        # FTS rows are maintained explicitly, so prune them while the source's
        # event primary keys are still available to identify the matching rows.
        self._session.execute(
            text(
                """
                DELETE FROM ctx_event_fts
                WHERE event_pk IN (
                    SELECT id FROM ctx_event WHERE source_id = :source_id
                )
                """
            ),
            {"source_id": source_id},
        )
        self._session.execute(delete(ctx_file_touched).where(ctx_file_touched.c.source_id == source_id))
        self._session.execute(delete(ctx_event).where(ctx_event.c.source_id == source_id))
        self._session.execute(delete(ctx_session).where(ctx_session.c.source_id == source_id))

    def insert_sessions(self, sessions: Iterable[Mapping[str, Any]]) -> int:
        rows = [dict(values) for values in sessions]
        if not rows:
            return 0
        self._session.execute(sqlite_insert(ctx_session), rows)
        return len(rows)

    def insert_events_with_files(
        self,
        event_rows: Iterable[tuple[Mapping[str, Any], Iterable[str]]],
    ) -> tuple[int, int]:
        pairs = [(dict(values), list(paths)) for values, paths in event_rows]
        rows = [values for values, _paths in pairs]
        if not rows:
            return 0, 0

        # Source rows are cleared before event writes, so inserts are sufficient
        # and avoid per-row conflict handling or per-row primary-key lookups.
        self._session.execute(sqlite_insert(ctx_event), rows)
        event_pk_by_key = self._event_primary_keys(rows)
        self._insert_fts_rows(rows, event_pk_by_key)
        files_written = self._insert_file_rows(pairs)
        return len(rows), files_written

    def _event_primary_keys(self, rows: Sequence[Mapping[str, Any]]) -> dict[tuple[int, str, str], int]:
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
            raise RuntimeError(f"ctx event primary key lookup missed inserted events: {missing[:3]}")
        return found

    def _insert_fts_rows(
        self, rows: Sequence[Mapping[str, Any]], event_pk_by_key: Mapping[tuple[int, str, str], int]
    ) -> None:
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

    def _insert_file_rows(self, pairs: Sequence[tuple[Mapping[str, Any], list[str]]]) -> int:
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
        if not file_rows:
            return 0
        self._session.execute(sqlite_insert(ctx_file_touched), file_rows)
        return len(file_rows)


def _event_key(row: Mapping[str, Any]) -> tuple[int, str, str]:
    return (int(row["source_id"]), str(row["source_table"]), str(row["event_id"]))
