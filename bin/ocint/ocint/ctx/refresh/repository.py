from pathlib import Path

from sqlalchemy import desc, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from ocint.ctx.db.schema import ctx_refresh_state, ctx_source
from ocint.ctx.models import (
    CtxRefreshAttemptStatus,
    CtxRefreshFailure,
    CtxRefreshState,
    CtxRefreshSuccess,
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

    def aggregate_state(self) -> CtxRefreshState | None:
        """Return status-oriented refresh metadata aggregated across imported sources."""
        latest_success = (
            self._session.execute(
                select(ctx_refresh_state)
                .where(ctx_refresh_state.c.latest_success_completed_at.is_not(None))
                .order_by(desc(ctx_refresh_state.c.latest_success_completed_at))
                .limit(1)
            )
            .mappings()
            .one_or_none()
        )
        latest_attempt = (
            self._session.execute(
                select(ctx_refresh_state)
                .where(ctx_refresh_state.c.latest_attempt_started_at.is_not(None))
                .order_by(desc(ctx_refresh_state.c.latest_attempt_started_at))
                .limit(1)
            )
            .mappings()
            .one_or_none()
        )
        latest_failure = (
            self._session.execute(
                select(ctx_refresh_state)
                .where(ctx_refresh_state.c.latest_failed_at.is_not(None))
                .order_by(desc(ctx_refresh_state.c.latest_failed_at))
                .limit(1)
            )
            .mappings()
            .one_or_none()
        )
        if latest_success is None and latest_attempt is None and latest_failure is None:
            return None
        success_state = (
            CtxRefreshState.model_validate(latest_success) if latest_success is not None else CtxRefreshState()
        )
        attempt_state = (
            CtxRefreshState.model_validate(latest_attempt) if latest_attempt is not None else CtxRefreshState()
        )
        failure_state = (
            CtxRefreshState.model_validate(latest_failure) if latest_failure is not None else CtxRefreshState()
        )
        return CtxRefreshState(
            source_id=success_state.source_id or attempt_state.source_id or failure_state.source_id,
            latest_attempt_started_at=attempt_state.latest_attempt_started_at,
            latest_attempt_completed_at=attempt_state.latest_attempt_completed_at,
            latest_attempt_status=attempt_state.latest_attempt_status,
            latest_success_started_at=success_state.latest_success_started_at,
            latest_success_completed_at=success_state.latest_success_completed_at,
            latest_success_checkpoint_payload=success_state.latest_success_checkpoint_payload,
            source_watermark_payload=success_state.source_watermark_payload,
            latest_failed_at=failure_state.latest_failed_at,
            latest_error_message=failure_state.latest_error_message,
        )

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
            "latest_attempt_started_at": failure.attempted_at,
            "latest_attempt_completed_at": failure.attempted_at,
            "latest_attempt_status": CtxRefreshAttemptStatus.FAILED.value,
            "latest_failed_at": failure.attempted_at,
            "latest_error_message": failure.error_message,
        }
        statement = sqlite_insert(ctx_refresh_state).values(values)
        self._session.execute(
            statement.on_conflict_do_update(
                index_elements=[ctx_refresh_state.c.source_id],
                set_={key: values[key] for key in values if key != "source_id"},
            )
        )
