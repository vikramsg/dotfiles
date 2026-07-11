# ocint ctx Spec

## Purpose

`ocint ctx` imports OpenCode history into an ocint-owned SQLite database, then
searches and inspects that imported history.

The ocint-owned database is resolved from `OCINT_CTX_DB` when set. Otherwise it
uses `$XDG_STATE_HOME/ocint/ctx.sqlite`, defaulting to
`~/.local/state/ocint/ctx.sqlite`.

Alembic manages migrations for the ocint-owned database only. OpenCode SQLite is
always a read-only source.

## Repository Session Workflow

Command handlers own database/session lifecycle.

The handler workflow is:

- Resolve the ctx database path.
- Open the SQLAlchemy connection/session with the required read or write scope.
- Run Alembic migrations when the command needs a writable ctx database.
- Create typed repository handles for that session.
- Pass the workflow's repository handle into its workflow function.
- Commit, roll back, or close the session at the command boundary.

Workflow functions do not create engines, open sessions, run migrations, or
import database-session modules directly. Persistence happens only through the
typed repository passed by the handler.

## Import Workflow

`ocint ctx import` updates the ocint-owned ctx database from OpenCode history.

The workflow is:

- Resolve and open the ctx database in write mode.
- Run Alembic migrations.
- Resolve the OpenCode database path.
- Open OpenCode SQLite read-only.
- Read OpenCode sessions, messages, and parts. Raw OpenCode `event` rows are not part of the ctx import source contract.
- Normalize message/part transcript rows into ctx history records.
- Upsert sources, sessions, events, files touched, citations, checkpoints, and
  search projections.
- Return import counts and checkpoint status.

Imports must be safe to run repeatedly. Repeated imports should be idempotent and
incremental where checkpoint data allows it.

### Import Interface

```python
from ocint.ctx.importing.repository import CtxImportRepository
from ocint.ctx.models import (
    CtxImportEvent,
    CtxImportProgress,
    CtxImportRequest,
    CtxImportResult,
    CtxRefreshSuccess,
)


class OpenCodeHistorySource(Protocol):
    def session_keys(self) -> list[OpenCodeSessionKey]: ...

    def sessions(self) -> list[OpenCodeSessionRow]: ...

    def sessions_for_ids(self, ids: Sequence[str]) -> list[OpenCodeSessionRow]: ...

    def transcript_event_keys(self) -> list[OpenCodeTranscriptEventKey]: ...

    def transcript_event_batches(self, batch_size: int) -> Iterator[list[OpenCodeTranscriptEventRow]]: ...

    def transcript_event_batches_for_keys(
        self,
        keys: Sequence[tuple[str, str]],
        batch_size: int,
    ) -> Iterator[list[OpenCodeTranscriptEventRow]]: ...

    def session_message_keys(self) -> list[OpenCodeSessionMessageKey]: ...

    def source_table_watermarks(self) -> dict[str, dict[str, int | None]]: ...


class CtxRefreshStateWriter(Protocol):
    def mark_attempt_success(self, source_id: int, success: CtxRefreshSuccess) -> None: ...


def import_history_events(
    request: CtxImportRequest,
    repository: CtxImportRepository,
    refresh_repository: CtxRefreshStateWriter,
    source: OpenCodeHistorySource,
) -> Iterator[CtxImportEvent]:
    ...
```

`CtxImportRequest` carries `source_db_path` and `attempt_started_at`.

## Search Index Workflow

`index` means physical search projections, not a domain package.

The import workflow maintains the search index by writing:

- FTS rows for searchable event/session text.
- Metadata indexes for session, workspace, time, event type, and source lookup.
- File path lookup rows for file-scoped search.
- Citation/provenance rows used by search, show, and locate results.

Search reads these projections. Search does not update index rows.

## Search Workflow

`ocint ctx search` searches imported ctx history.

The workflow is:

- Resolve and open the ctx database.
- The command handler may refresh or import before search based on `--refresh`
  (`auto` or `off`). Default `auto` imports a missing index in the foreground,
  searches a ready index immediately, and refreshes a stale ready index in the
  background (TTL default 60m).
- Call search with the user query, filters, and search repository.
- Search reads indexed ctx history.
- Return cited results with follow-up commands.

Search itself does not trigger import. Refresh-before-search is command
orchestration, not search behavior.

### Search Interface

```python
from ocint.ctx.models import CtxSearchRequest, CtxSearchResult
from ocint.ctx.search.repository import CtxSearchRepository


def search_history(request: CtxSearchRequest, repository: CtxSearchRepository) -> list[CtxSearchResult]:
    ...
```

`CtxSearchRequest` includes `query`, required `content` / `limit`, optional
`session_id` / `workspace` / `file` / `since`, `terms`, `include_subagents`,
`active_session_id`, and `include_current_session`. CLI defaults are
`--content text` and `--limit 20`.

## Show Workflow

`ocint ctx show session` and `ocint ctx show event` read imported ctx history and
render transcript context.

The workflow is:

- Resolve and open the ctx database.
- With no session ID, list recent sessions through the show repository.
- With a session ID, load that session transcript.
- For events, load neighboring session events.
- Render text, markdown, or JSON.

### Show Interface

```python
from ocint.ctx.models import (
    CtxEventContext,
    CtxSession,
    CtxShowSessionRequest,
    CtxTranscript,
)
from ocint.ctx.show.repository import CtxShowRepository


def show_session_request(
    repository: CtxShowRepository, request: CtxShowSessionRequest
) -> list[CtxSession] | CtxTranscript:
    ...


def show_session_history(repository: CtxShowRepository, session_id: str) -> CtxTranscript:
    ...


def show_event_history(repository: CtxShowRepository, event_id: str, *, window: int = 5) -> CtxEventContext:
    ...
```

`CtxShowSessionRequest` is either a recent-sessions request (`limit`) or a
transcript request (`session_id`).

## Locate Workflow

`ocint ctx locate session` and `ocint ctx locate event` return provenance for
imported ctx history.

The workflow is:

- Resolve and open the ctx database.
- Load source, session, and event metadata through the locate repository.
- Return provider, source path, source table, native IDs, and citation data.

### Locate Interface

```python
from ocint.ctx.locate.repository import CtxLocateRepository
from ocint.ctx.models import CtxLocateResult


def locate_session(repository: CtxLocateRepository, session_id: str) -> CtxLocateResult | None:
    ...


def locate_event(repository: CtxLocateRepository, event_id: str) -> CtxLocateResult | None:
    ...
```

## SQL Workflow

`ocint ctx sql` runs read-only structured queries over imported ctx history.

The workflow is:

- Resolve and open the ctx database read-only.
- Expose stable ctx views or tables for inspection.
- Validate the SQL as a single read-only statement.
- Execute with SQLite read-only protections.
- Return table, JSON, CSV, or raw output.

### SQL Interface

```python
from ocint.ctx.sql.models import CtxSqlConfig
from ocint.ctx.sql.repository import CtxSqlRepository


def run_ctx_sql(repository: CtxSqlRepository, sql: str, config: CtxSqlConfig) -> list[dict[str, object]]:
    ...
```
