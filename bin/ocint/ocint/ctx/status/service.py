from ocint._errors import OcintError
from ocint.ctx.models import CtxRefreshConfig, CtxRefreshState, CtxSource, CtxStatus
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
    refresh_state: CtxRefreshState | None,
    refresh_in_progress: bool,
    now_ms: int,
) -> CtxStatus:
    require_ctx_index_ready(repository, config, expected_revision)
    status = repository.status()
    freshness = calculate_freshness(refresh_state, ttl_ms=refresh_config.ttl_ms, now_ms=now_ms)
    return status.model_copy(
        update={
            "refresh_ttl_ms": refresh_config.ttl_ms,
            "refresh_freshness": freshness,
            "refresh_in_progress": refresh_in_progress,
            "latest_success_started_at": refresh_state.latest_success_started_at if refresh_state else None,
            "latest_success_completed_at": refresh_state.latest_success_completed_at if refresh_state else None,
            "latest_attempt_started_at": refresh_state.latest_attempt_started_at if refresh_state else None,
            "latest_attempt_completed_at": refresh_state.latest_attempt_completed_at if refresh_state else None,
            "latest_attempt_status": refresh_state.latest_attempt_status if refresh_state else None,
            "latest_failed_at": refresh_state.latest_failed_at if refresh_state else None,
            "latest_error_message": refresh_state.latest_error_message if refresh_state else None,
            "checkpoint_summary": _checkpoint_summary(refresh_state),
        }
    )


def list_sources(repository: CtxStatusRepository, config: CtxSqlConfig, expected_revision: str) -> list[CtxSource]:
    require_ctx_index_ready(repository, config, expected_revision)
    return repository.sources()


def _checkpoint_summary(refresh_state: CtxRefreshState | None) -> str | None:
    if refresh_state is None or refresh_state.latest_success_checkpoint_payload is None:
        return None
    return refresh_state.latest_success_checkpoint_payload[:240]
