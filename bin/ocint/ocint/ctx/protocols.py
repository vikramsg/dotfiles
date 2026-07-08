from collections.abc import Mapping
from pathlib import Path
from typing import Any, Protocol

from ocint.ctx.models import CtxImportBatch, CtxImportWriteResult, CtxSearchCandidate, CtxSource, CtxStatus


class CtxRepositoryProtocol(Protocol):
    db_path: Path


class CtxImportRepositoryProtocol(CtxRepositoryProtocol, Protocol):
    def replace_source_projection(self, batch: CtxImportBatch) -> CtxImportWriteResult: ...


class CtxSearchRepositoryProtocol(CtxRepositoryProtocol, Protocol):
    def search_events(
        self,
        *,
        query: str,
        query_tokens: list[str],
        required_terms: list[str],
        since_ms: int | None,
        session_id: str | None,
        workspace: str | None,
        file_filter: str | None,
        include_subagents: bool,
        limit: int | None,
    ) -> list[CtxSearchCandidate]: ...


class CtxShowRepositoryProtocol(CtxRepositoryProtocol, Protocol):
    def find_event(self, event_id: str) -> CtxSearchCandidate | None: ...

    def find_session(self, session_id: str) -> Mapping[str, Any] | None: ...

    def session_events(self, *, source_id: int, session_id: str) -> list[CtxSearchCandidate]: ...

    def event_window(self, selected: CtxSearchCandidate, *, window: int) -> list[CtxSearchCandidate]: ...


class CtxLocateRepositoryProtocol(CtxRepositoryProtocol, Protocol):
    def find_event(self, event_id: str) -> CtxSearchCandidate | None: ...

    def find_session(self, session_id: str) -> Mapping[str, Any] | None: ...


class CtxStatusRepositoryProtocol(CtxRepositoryProtocol, Protocol):
    def status(self, *, source_db_path: Path | None = None) -> CtxStatus: ...

    def sources(self) -> list[CtxSource]: ...

    def index_ready(self) -> bool: ...


class CtxSqlProjectionRepositoryProtocol(CtxRepositoryProtocol, Protocol):
    def load_stable_projection_rows(self) -> dict[str, list[dict[str, Any]]]: ...
