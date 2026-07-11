from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field


class StateModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class UsageTokens(StateModel):
    input: int = 0
    output: int = 0
    reasoning: int = 0
    cache_read: int = 0
    cache_write: int = 0
    total: int = 0


class StateSummary(StateModel):
    db_path: Path
    sessions: int = 0
    messages: int = 0
    cost: float = 0.0
    tokens: UsageTokens = Field(default_factory=UsageTokens)


class StateSessionUsage(StateModel):
    session_id: str
    first_seen: datetime
    last_seen: datetime
    messages: int = 0
    cost: float = 0.0
    tokens: UsageTokens = Field(default_factory=UsageTokens)


class StateDetailedProjectUsage(StateModel):
    project_id: str | None = None
    worktree: str | None = None
    sessions: int = 0
    assistant_messages: int = 0
    cost: float = 0.0
    tokens: UsageTokens = Field(default_factory=UsageTokens)


class StateDetailedAgentUsage(StateModel):
    agent: str
    kind: str
    sessions: int = 0
    assistant_messages: int = 0
    cost: float = 0.0
    tokens: UsageTokens = Field(default_factory=UsageTokens)


class StateDetailedProjectAgentUsage(StateModel):
    project_id: str | None = None
    worktree: str | None = None
    agent: str
    kind: str
    sessions: int = 0
    assistant_messages: int = 0
    cost: float = 0.0
    tokens: UsageTokens = Field(default_factory=UsageTokens)


class StateDetailed(StateModel):
    db_path: Path
    opencode_total_cost: float = 0.0
    message_attributed_cost: float = 0.0
    projects: list[StateDetailedProjectUsage] = Field(default_factory=list)
    agents: list[StateDetailedAgentUsage] = Field(default_factory=list)
    project_agents: list[StateDetailedProjectAgentUsage] = Field(default_factory=list)
