from ocint.ctx.models import (
    CtxRefreshAction,
    CtxRefreshDecision,
    CtxRefreshFreshness,
    CtxRefreshPolicyInput,
    CtxRefreshState,
    RefreshMode,
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
