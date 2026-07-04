from collections import defaultdict
from datetime import UTC, date, datetime
from typing import Iterable

from ocint._timeutil import UsageWindow
from ocint.opencode.models import OpenCodePartRow, OpenCodeTokenPayload
from ocint.opencode.repository import OpenCodeRepository
from ocint.state.models import StateDailyUsage, StateModelUsage, StateSessionUsage, StateSummary, UsageTokens


class StateService:
    def __init__(self, repository: OpenCodeRepository) -> None:
        self._repository = repository

    def summary(self, window: UsageWindow) -> StateSummary:
        parts = list(self._usage_parts(window))
        return StateSummary(
            db_path=self._repository.db_path,
            since=window.since,
            until=window.until,
            sessions=len({part.session_id for part in parts if part.session_id}),
            llm_steps=len(parts),
            cost=sum(float(part.data.cost or 0.0) for part in parts),
            tokens=_sum_tokens(parts),
        )

    def daily(self, window: UsageWindow) -> list[StateDailyUsage]:
        buckets: dict[date, list[OpenCodePartRow]] = defaultdict(list)
        for part in self._usage_parts(window):
            if part.time_created is not None:
                buckets[_day(part.time_created)].append(part)
        return [
            StateDailyUsage(
                day=day,
                sessions=len({part.session_id for part in parts if part.session_id}),
                llm_steps=len(parts),
                cost=sum(float(part.data.cost or 0.0) for part in parts),
                tokens=_sum_tokens(parts),
            )
            for day, parts in sorted(buckets.items())
        ]

    def models(self, window: UsageWindow) -> list[StateModelUsage]:
        messages = self._repository.messages_by_id()
        buckets: dict[tuple[str, str], list[OpenCodePartRow]] = defaultdict(list)
        for part in self._usage_parts(window):
            message = messages.get(part.message_id or "")
            provider = message.data.provider_id if message and message.data.provider_id else "(unknown)"
            model = message.data.model_id if message and message.data.model_id else "(unknown)"
            buckets[(provider, model)].append(part)
        rows = [
            StateModelUsage(
                provider=provider,
                model=model,
                sessions=len({part.session_id for part in parts if part.session_id}),
                llm_steps=len(parts),
                cost=sum(float(part.data.cost or 0.0) for part in parts),
                tokens=_sum_tokens(parts),
            )
            for (provider, model), parts in buckets.items()
        ]
        return sorted(rows, key=lambda row: (-row.cost, -row.llm_steps, row.provider, row.model))

    def sessions(self, window: UsageWindow) -> list[StateSessionUsage]:
        buckets: dict[str, list[OpenCodePartRow]] = defaultdict(list)
        for part in self._usage_parts(window):
            if part.session_id:
                buckets[part.session_id].append(part)
        rows = []
        for session_id, parts in buckets.items():
            times = [part.time_created for part in parts if part.time_created is not None]
            if not times:
                continue
            rows.append(
                StateSessionUsage(
                    session_id=session_id,
                    first_seen=_dt(min(times)),
                    last_seen=_dt(max(times)),
                    llm_steps=len(parts),
                    cost=sum(float(part.data.cost or 0.0) for part in parts),
                    tokens=_sum_tokens(parts),
                )
            )
        return sorted(rows, key=lambda row: (row.last_seen, row.session_id), reverse=True)

    def query(self, sql: str) -> list[dict[str, object]]:
        return self._repository.query(sql)

    def _usage_parts(self, window: UsageWindow) -> Iterable[OpenCodePartRow]:
        for part in self._repository.parts():
            if part.data.type != "step-finish":
                continue
            if part.time_created is None:
                continue
            if window.start_ms is not None and part.time_created < window.start_ms:
                continue
            if window.end_ms is not None and part.time_created >= window.end_ms:
                continue
            yield part


def _sum_tokens(parts: Iterable[OpenCodePartRow]) -> UsageTokens:
    totals = UsageTokens()
    for part in parts:
        tokens = _tokens(part.data.tokens)
        totals = UsageTokens(
            input=totals.input + tokens.input,
            output=totals.output + tokens.output,
            reasoning=totals.reasoning + tokens.reasoning,
            cache_read=totals.cache_read + tokens.cache_read,
            cache_write=totals.cache_write + tokens.cache_write,
            total=totals.total + tokens.total,
        )
    return totals


def _tokens(payload: OpenCodeTokenPayload) -> UsageTokens:
    total = payload.total
    if total is None:
        total = payload.input + payload.output + payload.reasoning + payload.cache.read + payload.cache.write
    return UsageTokens(
        input=payload.input,
        output=payload.output,
        reasoning=payload.reasoning,
        cache_read=payload.cache.read,
        cache_write=payload.cache.write,
        total=total,
    )


def _day(timestamp_ms: int) -> date:
    return datetime.fromtimestamp(timestamp_ms / 1000, tz=UTC).date()


def _dt(timestamp_ms: int) -> datetime:
    return datetime.fromtimestamp(timestamp_ms / 1000, tz=UTC)
