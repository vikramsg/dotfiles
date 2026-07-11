from datetime import UTC, datetime

from ocint._timeutil import UsageWindow
from ocint.opencode.models import OpenCodeUsageSession
from ocint.opencode.repository import OpenCodeRepository
from ocint.state.models import (
    StateDetailed,
    StateDetailedAgentUsage,
    StateDetailedProjectAgentUsage,
    StateDetailedProjectUsage,
    StateSessionUsage,
    StateSummary,
    UsageTokens,
)


class StateService:
    def __init__(self, repository: OpenCodeRepository) -> None:
        self._repository = repository

    def summary(self, window: UsageWindow) -> StateSummary:
        sessions = self._repository.usage_sessions(start_ms=window.start_ms)
        return StateSummary(
            db_path=self._repository.db_path,
            sessions=len(sessions),
            messages=sum(session.messages for session in sessions),
            cost=sum(session.cost for session in sessions),
            tokens=_sum_tokens(sessions),
        )

    def sessions(self, window: UsageWindow) -> list[StateSessionUsage]:
        return [
            StateSessionUsage(
                session_id=session.id,
                first_seen=_dt(session.time_created),
                last_seen=_dt(session.time_updated),
                messages=session.messages,
                cost=session.cost,
                tokens=_sum_tokens([session]),
            )
            for session in self._repository.usage_sessions(start_ms=window.start_ms)
        ]

    def detailed(self, window: UsageWindow) -> StateDetailed:
        detailed_usage = self._repository.detailed_usage(start_ms=window.start_ms)
        projects = [
            StateDetailedProjectUsage(
                project_id=row.project_id,
                worktree=row.worktree,
                sessions=row.sessions,
                assistant_messages=row.assistant_messages,
                cost=row.cost,
                tokens=UsageTokens.model_validate(row.tokens.model_dump()),
            )
            for row in detailed_usage.projects
        ]
        agents = [
            StateDetailedAgentUsage(
                agent=row.agent,
                kind=row.kind,
                sessions=row.sessions,
                assistant_messages=row.assistant_messages,
                cost=row.cost,
                tokens=UsageTokens.model_validate(row.tokens.model_dump()),
            )
            for row in detailed_usage.agents
        ]
        project_agents = [
            StateDetailedProjectAgentUsage(
                project_id=row.project_id,
                worktree=row.worktree,
                agent=row.agent,
                kind=row.kind,
                sessions=row.sessions,
                assistant_messages=row.assistant_messages,
                cost=row.cost,
                tokens=UsageTokens.model_validate(row.tokens.model_dump()),
            )
            for row in detailed_usage.project_agents
        ]
        return StateDetailed(
            db_path=self._repository.db_path,
            message_attributed_cost=sum(project.cost for project in projects),
            projects=projects,
            agents=agents,
            project_agents=project_agents,
        )

    def query(self, sql: str) -> list[dict[str, object]]:
        return self._repository.query(sql)


def _sum_tokens(sessions: list[OpenCodeUsageSession]) -> UsageTokens:
    totals = UsageTokens()
    for session in sessions:
        totals = UsageTokens(
            input=totals.input + session.tokens_input,
            output=totals.output + session.tokens_output,
            reasoning=totals.reasoning + session.tokens_reasoning,
            cache_read=totals.cache_read + session.tokens_cache_read,
            cache_write=totals.cache_write + session.tokens_cache_write,
            total=totals.total
            + session.tokens_input
            + session.tokens_output
            + session.tokens_reasoning
            + session.tokens_cache_read
            + session.tokens_cache_write,
        )
    return totals


def _dt(timestamp_ms: int) -> datetime:
    return datetime.fromtimestamp(timestamp_ms / 1000, tz=UTC)
