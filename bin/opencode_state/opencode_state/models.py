from datetime import date, datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field


class OutputModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ResolvedPaths(OutputModel):
    config_path: Path
    db_path: Path
    config_exists: bool
    db_exists: bool


class UsageTokens(OutputModel):
    input: int = 0
    output: int = 0
    reasoning: int = 0
    cache_read: int = 0
    cache_write: int = 0
    total: int = 0


class UsageSummary(OutputModel):
    db_path: Path
    since: date | None = None
    until: date | None = None
    sessions: int = 0
    llm_steps: int = 0
    cost: float = 0.0
    tokens: UsageTokens = Field(default_factory=UsageTokens)


class DailyUsage(OutputModel):
    day: date
    sessions: int = 0
    llm_steps: int = 0
    cost: float = 0.0
    tokens: UsageTokens = Field(default_factory=UsageTokens)


class ModelUsage(OutputModel):
    provider: str
    model: str
    sessions: int = 0
    llm_steps: int = 0
    cost: float = 0.0
    tokens: UsageTokens = Field(default_factory=UsageTokens)


class SessionUsage(OutputModel):
    session_id: str
    first_seen: datetime
    last_seen: datetime
    llm_steps: int = 0
    cost: float = 0.0
    tokens: UsageTokens = Field(default_factory=UsageTokens)
