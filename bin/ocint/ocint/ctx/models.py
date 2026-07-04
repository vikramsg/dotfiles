from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field


class CtxModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class CtxStatus(CtxModel):
    provider: str = "opencode"
    db_path: Path
    db_exists: bool
    sessions: int = 0
    primary_sessions: int = 0
    events: int = 0


class CtxSource(CtxModel):
    provider: str = "opencode"
    source_type: str
    name: str
    path: str | None = None
    count: int = 0


class CtxSession(CtxModel):
    provider: str = "opencode"
    session_id: str
    parent_id: str | None = None
    title: str | None = None
    workspace: str | None = None
    time_created: int | None = None
    time_updated: int | None = None
    event_count: int = 0


class CtxSearchRequest(CtxModel):
    query: str
    session_id: str | None = None
    workspace: str | None = None
    file: str | None = None
    since: str | None = None
    terms: list[str] = Field(default_factory=list)
    include_subagents: bool = False
    limit: int | None = 50


class CtxSearchResult(CtxModel):
    provider: str = "opencode"
    session_id: str
    event_id: str
    source_table: str
    event_type: str
    time_created: int | None = None
    title: str | None = None
    workspace: str | None = None
    source_path: str | None = None
    snippet: str
    citation: str
    follow_up: str


class CtxEventDetail(CtxModel):
    provider: str = "opencode"
    session_id: str
    event_id: str
    source_table: str
    event_type: str
    time_created: int | None = None
    title: str | None = None
    workspace: str | None = None
    source_path: str | None = None
    snippet: str
    text: str
    citation: str
    follow_up: str


class CtxTranscript(CtxModel):
    provider: str = "opencode"
    session: CtxSession
    events: list[CtxEventDetail] = Field(default_factory=list)


class CtxEventContext(CtxModel):
    provider: str = "opencode"
    selected: CtxEventDetail
    events: list[CtxEventDetail] = Field(default_factory=list)


class CtxLocateResult(CtxModel):
    provider: str = "opencode"
    kind: str
    id: str
    db_path: Path
    source_table: str | None = None
    session_id: str | None = None
    source_path: str | None = None
    citation: str | None = None
