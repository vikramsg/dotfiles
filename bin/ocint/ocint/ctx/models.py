from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class CtxModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class CtxStatus(CtxModel):
    provider: str = "opencode"
    db_path: Path
    db_exists: bool
    index_ready: bool = False
    sessions: int = 0
    primary_sessions: int = 0
    events: int = 0
    sources: int = 0
    source_db_path: Path | None = None
    source_db_exists: bool = False


class CtxSource(CtxModel):
    provider: str = "opencode"
    source_type: str
    name: str
    path: str | None = None
    count: int = 0
    sessions: int = 0
    events: int = 0
    imported_at: int | None = None


class CtxImportRequest(CtxModel):
    source_db_path: Path
    full: bool = False


class CtxImportSource(CtxModel):
    provider: str = "opencode"
    source_type: str
    name: str
    source_path: str
    imported_at: int
    sessions: int = 0
    events: int = 0
    checkpoint_payload: str | None = None


class CtxImportBatch(CtxModel):
    source: CtxImportSource
    session_rows: list[dict[str, object]] = Field(default_factory=list)
    event_rows: list[dict[str, object]] = Field(default_factory=list)
    file_rows: list[dict[str, object]] = Field(default_factory=list)


class CtxImportWriteResult(CtxModel):
    source_id: int
    sessions_written: int = 0
    events_written: int = 0
    files_written: int = 0
    write_ms: float = 0.0
    fts_ms: float = 0.0


class CtxImportResult(CtxModel):
    provider: str = "opencode"
    ctx_db_path: Path
    source_db_path: Path
    sessions_seen: int = 0
    sessions_written: int = 0
    events_seen: int = 0
    events_written: int = 0
    files_written: int = 0
    checkpoint_updated: bool = False
    source_transform_ms: float = 0.0
    write_ms: float = 0.0
    fts_ms: float = 0.0


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


class CtxSearchCandidate(CtxModel):
    event_pk: int
    source_id: int
    provider: str = "opencode"
    session_id: str
    parent_id: str | None = None
    event_id: str
    source_table: str
    message_id: str | None = None
    event_type: str
    time_created: int | None = None
    time_updated: int | None = None
    title: str | None = None
    workspace: str | None = None
    source_path: str | None = None
    full_text: str
    search_text: str
    citation: str
    source_db_path: Path | None = None


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


class CtxBenchmarkBackendResult(CtxModel):
    backend: Literal["sqlite", "duckdb"]
    db_path: Path
    source_db_path: Path
    sessions_seen: int = 0
    sessions_written: int = 0
    events_seen: int = 0
    events_written: int = 0
    files_written: int = 0
    migration_ms: float = 0.0
    source_transform_ms: float = 0.0
    write_ms: float = 0.0
    fts_ms: float = 0.0
    total_import_ms: float = 0.0
    search_ms: float = 0.0
    search_results: int = 0
    index_bytes: int = 0


class CtxCompareResult(CtxModel):
    query: str
    source_db_path: Path
    results: list[CtxBenchmarkBackendResult] = Field(default_factory=list)
    speed_ratios: dict[str, float | None] = Field(default_factory=dict)
