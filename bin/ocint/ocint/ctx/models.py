from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field


class CtxModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class RefreshMode(StrEnum):
    AUTO = "auto"
    OFF = "off"


class SearchContentMode(StrEnum):
    TEXT = "text"
    TOOLS = "tools"
    ALL = "all"


class CtxRefreshAttemptStatus(StrEnum):
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"


class CtxRefreshFreshness(StrEnum):
    UNKNOWN = "unknown"
    FRESH = "fresh"
    STALE = "stale"


class CtxRefreshAction(StrEnum):
    FOREGROUND_REFRESH = "foreground_refresh"
    SEARCH_ONLY = "search_only"
    SEARCH_THEN_BACKGROUND_REFRESH = "search_then_background_refresh"


class CtxRefreshConfig(CtxModel):
    ttl_ms: int
    lock_path: Path
    log_path: Path


class CtxRefreshState(CtxModel):
    source_id: int | None = None
    latest_attempt_started_at: int | None = None
    latest_attempt_completed_at: int | None = None
    latest_attempt_status: CtxRefreshAttemptStatus | None = None
    latest_success_started_at: int | None = None
    latest_success_completed_at: int | None = None
    latest_success_checkpoint_payload: str | None = None
    source_watermark_payload: str | None = None
    latest_failed_at: int | None = None
    latest_error_message: str | None = None


class CtxSourceRefreshStatus(CtxModel):
    source_id: int
    provider: str = "opencode"
    source_type: str
    name: str
    source_path: str
    refresh_freshness: CtxRefreshFreshness = CtxRefreshFreshness.UNKNOWN
    latest_attempt_started_at: int | None = None
    latest_attempt_completed_at: int | None = None
    latest_attempt_status: CtxRefreshAttemptStatus | None = None
    latest_success_started_at: int | None = None
    latest_success_completed_at: int | None = None
    latest_success_checkpoint_payload: str | None = None
    source_watermark_payload: str | None = None
    latest_failed_at: int | None = None
    latest_error_message: str | None = None
    checkpoint_summary: str | None = None


class CtxRefreshPolicyInput(CtxModel):
    mode: RefreshMode
    ttl_ms: int
    index_ready: bool
    source_state: CtxRefreshState | None = None
    now_ms: int


class CtxRefreshDecision(CtxModel):
    action: CtxRefreshAction
    freshness: CtxRefreshFreshness


class CtxRefreshFailure(CtxModel):
    started_at: int
    completed_at: int
    error_message: str


class CtxRefreshSuccess(CtxModel):
    started_at: int
    completed_at: int
    checkpoint_payload: str | None = None
    source_watermark_payload: str | None = None


class CtxShowMode(StrEnum):
    LITE = "lite"
    FULL = "full"
    LOG = "log"


class CtxTranscriptFormat(StrEnum):
    TEXT = "text"
    MARKDOWN = "markdown"
    JSON = "json"


class CtxSqlOutputFormat(StrEnum):
    TABLE = "table"
    JSON = "json"
    CSV = "csv"
    RAW = "raw"


class CtxShowRecentSessionsRequest(CtxModel):
    limit: int = 10


class CtxShowSessionTranscriptRequest(CtxModel):
    session_id: str


type CtxShowSessionRequest = CtxShowRecentSessionsRequest | CtxShowSessionTranscriptRequest


class CtxDocTopic(CtxModel):
    name: str
    summary: str
    body: str


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
    observed_at_ms: int | None = None
    refresh_ttl_ms: int | None = None
    refresh_log_path: Path | None = None
    refresh_freshness: CtxRefreshFreshness = CtxRefreshFreshness.UNKNOWN
    refresh_in_progress: bool = False
    latest_success_started_at: int | None = None
    latest_success_completed_at: int | None = None
    latest_attempt_started_at: int | None = None
    latest_attempt_completed_at: int | None = None
    latest_attempt_status: CtxRefreshAttemptStatus | None = None
    latest_failed_at: int | None = None
    latest_error_message: str | None = None
    checkpoint_summary: str | None = None
    refresh_source_id: int | None = None
    refresh_source_provider: str | None = None
    refresh_source_type: str | None = None
    refresh_source_name: str | None = None
    refresh_source_path: str | None = None
    refresh_sources: list[CtxSourceRefreshStatus] = Field(default_factory=list)


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
    attempt_started_at: int


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


class CtxImportProgress(CtxModel):
    message: str
    current: int | None = None
    total: int | None = None


type CtxImportEvent = CtxImportProgress | CtxImportResult


class CtxSession(CtxModel):
    provider: str = "opencode"
    session_id: str
    parent_id: str | None = None
    title: str | None = None
    workspace: str | None = None
    time_created: int | None = None
    time_updated: int | None = None
    event_count: int = 0


class CtxSessionSummary(CtxModel):
    """Internal read model for session rows joined with imported source metadata."""

    session_pk: int
    source_id: int
    provider: str = "opencode"
    session_id: str
    parent_id: str | None = None
    title: str | None = None
    workspace: str | None = None
    time_created: int | None = None
    time_updated: int | None = None
    source_db_path: Path
    event_count: int = 0


class CtxSearchRequest(CtxModel):
    query: str
    content: SearchContentMode
    limit: int
    session_id: str | None = None
    workspace: str | None = None
    file: str | None = None
    since: str | None = None
    terms: list[str] = Field(default_factory=list)
    include_subagents: bool = False
    active_session_id: str | None = None
    include_current_session: bool = False


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
    payload_json: str
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
