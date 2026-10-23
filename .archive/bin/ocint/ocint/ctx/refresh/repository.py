from pathlib import Path

from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from ocint.ctx.db.schema import ctx_refresh_state, ctx_source
from ocint.ctx.models import (
    CtxRefreshAttemptStatus,
    CtxRefreshFailure,
    CtxRefreshState,
    CtxRefreshSuccess,
    CtxSourceRefreshStatus,
)


class CtxRefreshRepository:
    def __init__(self, session: Session, *, db_path: Path) -> None:
        self._session = session
        self.db_path = db_path

    def state_for_source(self, source_id: int) -> CtxRefreshState | None:
        row = (
            self._session.execute(select(ctx_refresh_state).where(ctx_refresh_state.c.source_id == source_id))
            .mappings()
            .one_or_none()
        )
        return CtxRefreshState.model_validate(row) if row is not None else None

    def state_for_source_identity(self, *, provider: str, source_type: str, source_path: str) -> CtxRefreshState | None:
        source_id = self._session.execute(
            select(ctx_source.c.id).where(
                ctx_source.c.provider == provider,
                ctx_source.c.source_type == source_type,
                ctx_source.c.source_path == source_path,
            )
        ).scalar_one_or_none()
        return self.state_for_source(int(source_id)) if source_id is not None else None

    def source_statuses(self) -> list[CtxSourceRefreshStatus]:
        statement = (
            select(
                ctx_source.c.id.label("source_id"),
                ctx_source.c.provider,
                ctx_source.c.source_type,
                ctx_source.c.name,
                ctx_source.c.source_path,
                ctx_refresh_state.c.latest_attempt_started_at,
                ctx_refresh_state.c.latest_attempt_completed_at,
                ctx_refresh_state.c.latest_attempt_status,
                ctx_refresh_state.c.latest_success_started_at,
                ctx_refresh_state.c.latest_success_completed_at,
                ctx_refresh_state.c.latest_success_checkpoint_payload,
                ctx_refresh_state.c.source_watermark_payload,
                ctx_refresh_state.c.latest_failed_at,
                ctx_refresh_state.c.latest_error_message,
            )
            .select_from(ctx_source.outerjoin(ctx_refresh_state, ctx_refresh_state.c.source_id == ctx_source.c.id))
            .order_by(ctx_source.c.provider, ctx_source.c.name, ctx_source.c.source_path)
        )
        return [CtxSourceRefreshStatus.model_validate(row) for row in self._session.execute(statement).mappings()]

    def mark_attempt_started(self, source_id: int, *, started_at: int) -> None:
        values = {
            "source_id": source_id,
            "latest_attempt_started_at": started_at,
            "latest_attempt_completed_at": None,
            "latest_attempt_status": CtxRefreshAttemptStatus.RUNNING.value,
        }
        statement = sqlite_insert(ctx_refresh_state).values(values)
        self._session.execute(
            statement.on_conflict_do_update(
                index_elements=[ctx_refresh_state.c.source_id],
                set_={key: values[key] for key in values if key != "source_id"},
            )
        )

    def mark_attempt_success(self, source_id: int, success: CtxRefreshSuccess) -> None:
        values = {
            "source_id": source_id,
            "latest_attempt_started_at": success.started_at,
            "latest_attempt_completed_at": success.completed_at,
            "latest_attempt_status": CtxRefreshAttemptStatus.SUCCESS.value,
            "latest_success_started_at": success.started_at,
            "latest_success_completed_at": success.completed_at,
            "latest_success_checkpoint_payload": success.checkpoint_payload,
            "source_watermark_payload": success.source_watermark_payload,
            "latest_error_message": None,
        }
        statement = sqlite_insert(ctx_refresh_state).values(values)
        self._session.execute(
            statement.on_conflict_do_update(
                index_elements=[ctx_refresh_state.c.source_id],
                set_={key: values[key] for key in values if key != "source_id"},
            )
        )

    def mark_attempt_failed(self, source_id: int, failure: CtxRefreshFailure) -> None:
        values = {
            "source_id": source_id,
            "latest_attempt_started_at": failure.started_at,
            "latest_attempt_completed_at": failure.completed_at,
            "latest_attempt_status": CtxRefreshAttemptStatus.FAILED.value,
            "latest_failed_at": failure.completed_at,
            "latest_error_message": failure.error_message,
        }
        statement = sqlite_insert(ctx_refresh_state).values(values)
        self._session.execute(
            statement.on_conflict_do_update(
                index_elements=[ctx_refresh_state.c.source_id],
                set_={key: values[key] for key in values if key != "source_id"},
            )
        )
