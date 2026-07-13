import sqlite3
import time
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy.exc import SQLAlchemyError

from ocint._errors import OcintError
from ocint.ctx.config import reject_ctx_source_db_alias
from ocint.ctx.db import ctx_session, migrate_ctx_db
from ocint.ctx.importing import (
    PROVIDER,
    SOURCE_NAME,
    SOURCE_TYPE,
    CtxImportRepository,
    import_history_events,
)
from ocint.ctx.models import (
    CtxImportProgress,
    CtxImportRequest,
    CtxImportResult,
    CtxRefreshAction,
    CtxRefreshDecision,
    CtxRefreshPolicyInput,
    CtxRefreshRunRequest,
    CtxRefreshState,
    CtxRefreshWorkerRequest,
    RefreshMode,
)
from ocint.ctx.refresh.lock import acquire_refresh_lock
from ocint.ctx.refresh.logging import create_refresh_logger
from ocint.ctx.refresh.repository import CtxRefreshRepository
from ocint.ctx.refresh.service import begin_refresh_attempt, decide_refresh_action, record_refresh_attempt_failure
from ocint.ctx.sql import CtxSqlConfig
from ocint.ctx.status import CtxStatusRepository
from ocint.opencode import OpenCodeRepository


def decide_auto_refresh(
    request: CtxRefreshRunRequest,
    sql_config: CtxSqlConfig,
    expected_revision: str,
) -> CtxRefreshDecision:
    """Load current readiness and apply automatic refresh policy."""
    index_ready, refresh_state = _ctx_index_ready_state(request, sql_config, expected_revision)
    return decide_refresh_action(
        CtxRefreshPolicyInput(
            mode=RefreshMode.AUTO,
            ttl_ms=request.refresh_config.ttl_ms,
            index_ready=index_ready,
            source_state=refresh_state,
            now_ms=_now_ms(),
        )
    )


def run_refresh_import(request: CtxRefreshRunRequest) -> Iterator[CtxImportProgress | CtxImportResult]:
    """Run a foreground refresh under the refresh lock."""
    reject_ctx_source_db_alias(ctx_db_path=request.ctx_db_path, source_db_path=request.source_db_path)
    with _refresh_lock(request, foreground=True) as lock_acquired:
        if not lock_acquired:
            return
        migrate_ctx_db(request.ctx_db_path)
        yield from _run_refresh_after_lock(request)


def run_refresh_worker(
    request: CtxRefreshWorkerRequest,
    sql_config: CtxSqlConfig,
    expected_revision: str,
) -> None:
    """Run one detached refresh worker without CLI or presentation concerns."""
    started_at = _now_ms()
    outcome = "started"
    logger = create_refresh_logger(run_id=request.run_id, enabled=request.log_jsonl)
    logger.info("refresh_worker_started")
    try:
        logger.info(
            "refresh_worker_configured",
            ctx_db=str(request.ctx_db_path),
            source_db=str(request.source_db_path),
            ttl_ms=request.refresh_config.ttl_ms,
            lock_path=str(request.refresh_config.lock_path),
        )
        reject_ctx_source_db_alias(ctx_db_path=request.ctx_db_path, source_db_path=request.source_db_path)
        with _refresh_lock(request, foreground=False) as lock_acquired:
            if not lock_acquired:
                outcome = "skipped"
                logger.info(
                    "refresh_skipped",
                    reason="lock_held",
                    ctx_db=str(request.ctx_db_path),
                    source_db=str(request.source_db_path),
                    lock_path=str(request.refresh_config.lock_path),
                )
                return
            logger.info(
                "refresh_lock_acquired",
                ctx_db=str(request.ctx_db_path),
                source_db=str(request.source_db_path),
                lock_path=str(request.refresh_config.lock_path),
            )
            logger.info("migration_started", ctx_db=str(request.ctx_db_path), source_db=str(request.source_db_path))
            migrate_ctx_db(request.ctx_db_path)
            logger.info("migration_completed", ctx_db=str(request.ctx_db_path), source_db=str(request.source_db_path))
            decision = decide_auto_refresh(request, sql_config, expected_revision)
            logger.info(
                "refresh_decision",
                ctx_db=str(request.ctx_db_path),
                source_db=str(request.source_db_path),
                action=decision.action.value,
                freshness=decision.freshness.value,
                ttl_ms=request.refresh_config.ttl_ms,
            )
            if decision.action == CtxRefreshAction.SEARCH_ONLY:
                outcome = "skipped"
                logger.info(
                    "refresh_skipped",
                    reason="fresh_after_lock_recheck",
                    ctx_db=str(request.ctx_db_path),
                    source_db=str(request.source_db_path),
                    freshness=decision.freshness.value,
                )
                return
            logger.info(
                "refresh_import_started",
                ctx_db=str(request.ctx_db_path),
                source_db=str(request.source_db_path),
            )
            for event in _run_refresh_after_lock(request):
                match event:
                    case CtxImportProgress():
                        logger.info(
                            "import_progress",
                            ctx_db=str(request.ctx_db_path),
                            source_db=str(request.source_db_path),
                            message=event.message,
                            current=event.current,
                            total=event.total,
                        )
                    case CtxImportResult():
                        outcome = "succeeded"
                        logger.info(
                            "refresh_succeeded",
                            ctx_db=str(request.ctx_db_path),
                            source_db=str(request.source_db_path),
                            sessions_seen=event.sessions_seen,
                            sessions_written=event.sessions_written,
                            events_seen=event.events_seen,
                            events_written=event.events_written,
                            files_written=event.files_written,
                            checkpoint_updated=event.checkpoint_updated,
                            duration_ms=_now_ms() - started_at,
                        )
    except (FileNotFoundError, ValueError, OcintError, sqlite3.Error, SQLAlchemyError) as error:
        outcome = "failed"
        logger.error(
            "refresh_failed",
            ctx_db=str(request.ctx_db_path),
            source_db=str(request.source_db_path),
            error_type=type(error).__name__,
            error=str(error) or type(error).__name__,
            duration_ms=_now_ms() - started_at,
        )
        raise
    finally:
        logger.info(
            "refresh_worker_finished",
            ctx_db=str(request.ctx_db_path),
            source_db=str(request.source_db_path),
            outcome=outcome,
            duration_ms=_now_ms() - started_at,
        )


def _ctx_index_ready_state(
    request: CtxRefreshRunRequest,
    sql_config: CtxSqlConfig,
    expected_revision: str,
) -> tuple[bool, CtxRefreshState | None]:
    try:
        reject_ctx_source_db_alias(ctx_db_path=request.ctx_db_path, source_db_path=request.source_db_path)
        if not request.ctx_db_path.exists():
            return False, None
        with ctx_session(request.ctx_db_path, commit=False) as session:
            status_repository = CtxStatusRepository(session, db_path=request.ctx_db_path)
            if not status_repository.index_ready(sql_config, expected_revision):
                return False, None
            refresh_repository = CtxRefreshRepository(session, db_path=request.ctx_db_path)
            return True, refresh_repository.state_for_source_identity(
                provider=PROVIDER,
                source_type=SOURCE_TYPE,
                source_path=str(request.source_db_path),
            )
    except FileNotFoundError, ValueError, OcintError, sqlite3.Error, SQLAlchemyError:
        return False, None


def _run_refresh_after_lock(request: CtxRefreshRunRequest) -> Iterator[CtxImportProgress | CtxImportResult]:
    started_at = _now_ms()
    source_id: int | None = None
    try:
        with ctx_session(request.ctx_db_path, commit=True) as session:
            source_id = begin_refresh_attempt(
                import_repository=CtxImportRepository(session, db_path=request.ctx_db_path),
                refresh_repository=CtxRefreshRepository(session, db_path=request.ctx_db_path),
                provider=PROVIDER,
                source_type=SOURCE_TYPE,
                name=SOURCE_NAME,
                source_path=request.source_db_path,
                started_at=started_at,
            )
        yield from _run_unlocked_import(request, attempt_started_at=started_at)
    except KeyboardInterrupt as error:
        _record_refresh_failure_if_started(request, source_id=source_id, started_at=started_at, error=error)
        raise
    except (FileNotFoundError, ValueError, OcintError, sqlite3.Error, SQLAlchemyError) as error:
        _record_refresh_failure_if_started(request, source_id=source_id, started_at=started_at, error=error)
        raise


def _record_refresh_failure_if_started(
    request: CtxRefreshRunRequest,
    *,
    source_id: int | None,
    started_at: int,
    error: BaseException,
) -> None:
    if source_id is None:
        return
    with ctx_session(request.ctx_db_path, commit=True) as session:
        record_refresh_attempt_failure(
            refresh_repository=CtxRefreshRepository(session, db_path=request.ctx_db_path),
            source_id=source_id,
            started_at=started_at,
            completed_at=_now_ms(),
            error=error,
        )


def _run_unlocked_import(
    request: CtxRefreshRunRequest, *, attempt_started_at: int
) -> Iterator[CtxImportProgress | CtxImportResult]:
    with ctx_session(request.ctx_db_path, commit=True) as session:
        yield from import_history_events(
            CtxImportRequest(source_db_path=request.source_db_path, attempt_started_at=attempt_started_at),
            CtxImportRepository(session, db_path=request.ctx_db_path),
            CtxRefreshRepository(session, db_path=request.ctx_db_path),
            OpenCodeRepository(request.source_db_path),
        )


@contextmanager
def _refresh_lock(request: CtxRefreshRunRequest, *, foreground: bool) -> Iterator[bool]:
    with acquire_refresh_lock(request.refresh_config.lock_path, blocking=False) as lock:
        if not lock.acquired:
            if foreground:
                raise OcintError(
                    f"ocint ctx refresh is already running for {request.ctx_db_path}; try again after it completes"
                )
            yield False
            return
        yield True


def _now_ms() -> int:
    return int(time.time() * 1000)
