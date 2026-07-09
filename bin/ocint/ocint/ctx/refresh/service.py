from pathlib import Path
from typing import Protocol

from ocint.ctx.models import (
    CtxRefreshAction,
    CtxRefreshDecision,
    CtxRefreshFailure,
    CtxRefreshFreshness,
    CtxRefreshPolicyInput,
    CtxRefreshState,
    RefreshMode,
)


class CtxRefreshSourceRepository(Protocol):
    def upsert_source(
        self,
        *,
        provider: str,
        source_type: str,
        name: str,
        source_path: str,
    ) -> int: ...


class CtxRefreshAttemptRepository(Protocol):
    def mark_attempt_started(self, source_id: int, *, started_at: int) -> None: ...

    def mark_attempt_failed(self, source_id: int, failure: CtxRefreshFailure) -> None: ...


def begin_refresh_attempt(
    *,
    import_repository: CtxRefreshSourceRepository,
    refresh_repository: CtxRefreshAttemptRepository,
    provider: str,
    source_type: str,
    name: str,
    source_path: Path,
    started_at: int,
) -> int:
    source_id = import_repository.upsert_source(
        provider=provider,
        source_type=source_type,
        name=name,
        source_path=str(source_path),
    )
    refresh_repository.mark_attempt_started(source_id, started_at=started_at)
    return source_id


def record_refresh_attempt_failure(
    *,
    refresh_repository: CtxRefreshAttemptRepository,
    source_id: int,
    started_at: int,
    completed_at: int,
    error: BaseException,
) -> None:
    refresh_repository.mark_attempt_failed(
        source_id,
        CtxRefreshFailure(started_at=started_at, completed_at=completed_at, error_message=_error_message(error)),
    )


def decide_refresh_action(policy: CtxRefreshPolicyInput) -> CtxRefreshDecision:
    """Decide search refresh orchestration from typed policy inputs only."""
    freshness = calculate_freshness(policy.source_state, ttl_ms=policy.ttl_ms, now_ms=policy.now_ms)
    match policy.mode:
        case RefreshMode.OFF:
            return CtxRefreshDecision(action=CtxRefreshAction.SEARCH_ONLY, freshness=freshness)
        case RefreshMode.AUTO:
            if not policy.index_ready or freshness == CtxRefreshFreshness.UNKNOWN:
                return CtxRefreshDecision(action=CtxRefreshAction.FOREGROUND_REFRESH, freshness=freshness)
            if freshness == CtxRefreshFreshness.STALE:
                return CtxRefreshDecision(
                    action=CtxRefreshAction.SEARCH_THEN_BACKGROUND_REFRESH,
                    freshness=freshness,
                )
            return CtxRefreshDecision(action=CtxRefreshAction.SEARCH_ONLY, freshness=freshness)


def calculate_freshness(state: CtxRefreshState | None, *, ttl_ms: int, now_ms: int) -> CtxRefreshFreshness:
    """Return freshness based only on the latest successful refresh completion time."""
    if state is None or state.latest_success_completed_at is None:
        return CtxRefreshFreshness.UNKNOWN
    if ttl_ms == 0:
        return CtxRefreshFreshness.STALE
    return (
        CtxRefreshFreshness.FRESH if now_ms - state.latest_success_completed_at < ttl_ms else CtxRefreshFreshness.STALE
    )


def _error_message(error: BaseException) -> str:
    message = str(error) or type(error).__name__
    if len(message) <= 1_000:
        return message
    return f"{message[:997]}..."
