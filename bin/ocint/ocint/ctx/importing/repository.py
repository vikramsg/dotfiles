from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from sqlalchemy import delete, select, text
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

    def upsert_sessions(self, sessions: Iterable[Mapping[str, Any]]) -> int:
        count = 0
        for values in sessions:
            statement = sqlite_insert(ctx_session).values(dict(values))
            excluded = statement.excluded
            self._session.execute(
                statement.on_conflict_do_update(
                    index_elements=[ctx_session.c.source_id, ctx_session.c.provider_session_id],
                    set_={
                        "provider": excluded.provider,
                        "session_id": excluded.session_id,
                        "parent_id": excluded.parent_id,
                        "title": excluded.title,
                        "workspace": excluded.workspace,
                        "time_created": excluded.time_created,
                        "time_updated": excluded.time_updated,
                        "source_path": excluded.source_path,
                        "payload_json": excluded.payload_json,
                    },
                )
            )
            count += 1
        return count

    def upsert_event_with_files(self, event_values: Mapping[str, Any], paths: Iterable[str]) -> int:
        values = dict(event_values)
        statement = sqlite_insert(ctx_event).values(values)
        excluded = statement.excluded
        self._session.execute(
            statement.on_conflict_do_update(
                index_elements=[ctx_event.c.source_id, ctx_event.c.source_table, ctx_event.c.event_id],
                set_={
                    "provider": excluded.provider,
                    "provider_session_id": excluded.provider_session_id,
                    "message_id": excluded.message_id,
                    "event_type": excluded.event_type,
                    "time_created": excluded.time_created,
                    "time_updated": excluded.time_updated,
                    "source_path": excluded.source_path,
                    "full_text": excluded.full_text,
                    "search_text": excluded.search_text,
                    "payload_json": excluded.payload_json,
                    "citation": excluded.citation,
                },
            )
        )
        event_pk = int(
            self._session.execute(
                select(ctx_event.c.id).where(
                    ctx_event.c.source_id == values["source_id"],
                    ctx_event.c.source_table == values["source_table"],
                    ctx_event.c.event_id == values["event_id"],
                )
            ).scalar_one()
        )
        self._replace_event_fts(event_pk=event_pk, values=values)
        self._replace_files(values=values, paths=paths)
        return event_pk

    def _replace_event_fts(self, *, event_pk: int, values: Mapping[str, Any]) -> None:
        self._session.execute(text("DELETE FROM ctx_event_fts WHERE event_pk = :event_pk"), {"event_pk": event_pk})
        self._session.execute(
            text(
                """
                INSERT INTO ctx_event_fts(search_text, event_pk, event_id, source_table)
                VALUES (:search_text, :event_pk, :event_id, :source_table)
                """
            ),
            {
                "search_text": values["search_text"],
                "event_pk": event_pk,
                "event_id": values["event_id"],
                "source_table": values["source_table"],
            },
        )

    def _replace_files(self, *, values: Mapping[str, Any], paths: Iterable[str]) -> None:
        self._session.execute(
            delete(ctx_file_touched).where(
                ctx_file_touched.c.source_id == values["source_id"],
                ctx_file_touched.c.source_table == values["source_table"],
                ctx_file_touched.c.event_id == values["event_id"],
            )
        )
        seen: set[str] = set()
        for path in paths:
            if not path or path in seen:
                continue
            seen.add(path)
            statement = sqlite_insert(ctx_file_touched).values(
                {
                    "source_id": values["source_id"],
                    "provider": values["provider"],
                    "path": path,
                    "provider_session_id": values["provider_session_id"],
                    "event_id": values["event_id"],
                    "source_table": values["source_table"],
                }
            )
            self._session.execute(statement.on_conflict_do_nothing())
