from pathlib import Path

from ocint._errors import OcintError
from ocint.ctx.models import CtxRefreshConfig, CtxRefreshState, CtxSource, CtxSourceRefreshStatus, CtxStatus
from ocint.ctx.refresh.service import calculate_freshness
from ocint.ctx.sql.models import CtxSqlConfig
from ocint.ctx.status.repository import CtxStatusRepository


def require_ctx_index_ready(repository: CtxStatusRepository, config: CtxSqlConfig, expected_revision: str) -> None:
    """Fail before read use cases query ctx tables that may not be migrated yet."""
    if not repository.index_ready(config, expected_revision):
        raise OcintError(f"ocint ctx index is not ready; run `ocint ctx import` first: {repository.db_path}")


def get_status(
    repository: CtxStatusRepository,
    config: CtxSqlConfig,
    expected_revision: str,
    *,
    refresh_config: CtxRefreshConfig,
    refresh_statuses: list[CtxSourceRefreshStatus],
    refresh_in_progress: bool,
    current_source_db_path: Path | None,
    current_source_db_exists: bool,
    now_ms: int,
) -> CtxStatus:
    require_ctx_index_ready(repository, config, expected_revision)
    status = repository.status()
    refresh_sources = _source_statuses_with_freshness(refresh_statuses, ttl_ms=refresh_config.ttl_ms, now_ms=now_ms)
    summary = _summary_refresh_status(refresh_sources)
    summary_state = _state_from_source_status(summary)
    freshness = calculate_freshness(summary_state, ttl_ms=refresh_config.ttl_ms, now_ms=now_ms)
    return status.model_copy(
        update={
            "source_db_path": current_source_db_path,
            "source_db_exists": current_source_db_exists,
            "observed_at_ms": now_ms,
            "refresh_ttl_ms": refresh_config.ttl_ms,
            "refresh_log_path": refresh_config.log_path,
            "refresh_freshness": freshness,
            "refresh_in_progress": refresh_in_progress,
            "latest_success_started_at": summary.latest_success_started_at if summary else None,
            "latest_success_completed_at": summary.latest_success_completed_at if summary else None,
            "latest_attempt_started_at": summary.latest_attempt_started_at if summary else None,
            "latest_attempt_completed_at": summary.latest_attempt_completed_at if summary else None,
            "latest_attempt_status": summary.latest_attempt_status if summary else None,
            "latest_failed_at": summary.latest_failed_at if summary else None,
            "latest_error_message": summary.latest_error_message if summary else None,
            "checkpoint_summary": summary.checkpoint_summary if summary else None,
            "refresh_source_id": summary.source_id if summary else None,
            "refresh_source_provider": summary.provider if summary else None,
            "refresh_source_type": summary.source_type if summary else None,
            "refresh_source_name": summary.name if summary else None,
            "refresh_source_path": summary.source_path if summary else None,
            "refresh_sources": refresh_sources,
        }
    )


def list_sources(repository: CtxStatusRepository, config: CtxSqlConfig, expected_revision: str) -> list[CtxSource]:
    require_ctx_index_ready(repository, config, expected_revision)
    return repository.sources()


def _source_statuses_with_freshness(
    statuses: list[CtxSourceRefreshStatus], *, ttl_ms: int, now_ms: int
) -> list[CtxSourceRefreshStatus]:
    return [
        status.model_copy(
            update={
                "refresh_freshness": calculate_freshness(
                    _state_from_source_status(status),
                    ttl_ms=ttl_ms,
                    now_ms=now_ms,
                ),
                "checkpoint_summary": _checkpoint_summary(status.latest_success_checkpoint_payload),
            }
        )
        for status in statuses
    ]


def _summary_refresh_status(statuses: list[CtxSourceRefreshStatus]) -> CtxSourceRefreshStatus | None:
    attempted = [status for status in statuses if status.latest_attempt_started_at is not None]
    if attempted:
        return max(attempted, key=lambda status: status.latest_attempt_started_at or -1)
    succeeded = [status for status in statuses if status.latest_success_completed_at is not None]
    if succeeded:
        return max(succeeded, key=lambda status: status.latest_success_completed_at or -1)
    return statuses[0] if statuses else None


def _state_from_source_status(status: CtxSourceRefreshStatus | None) -> CtxRefreshState | None:
    if status is None:
        return None
    return CtxRefreshState(
        source_id=status.source_id,
        latest_attempt_started_at=status.latest_attempt_started_at,
        latest_attempt_completed_at=status.latest_attempt_completed_at,
        latest_attempt_status=status.latest_attempt_status,
        latest_success_started_at=status.latest_success_started_at,
        latest_success_completed_at=status.latest_success_completed_at,
        latest_success_checkpoint_payload=status.latest_success_checkpoint_payload,
        source_watermark_payload=status.source_watermark_payload,
        latest_failed_at=status.latest_failed_at,
        latest_error_message=status.latest_error_message,
    )


def _checkpoint_summary(checkpoint_payload: str | None) -> str | None:
    if checkpoint_payload is None:
        return None
    return checkpoint_payload[:240]
