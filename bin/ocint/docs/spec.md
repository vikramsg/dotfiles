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
- Read OpenCode sessions, messages, parts, and events.
- Normalize source rows into ctx history records.
- Upsert sources, sessions, events, files touched, citations, checkpoints, and
  search projections.
- Return import counts and checkpoint status.

Imports must be safe to run repeatedly. Repeated imports should be idempotent and
incremental where checkpoint data allows it.

### Import Interface

```python
from pathlib import Path
from typing import Literal

from pydantic import BaseModel


class ImportRequest(BaseModel):
    source: Literal["opencode"] = "opencode"
    source_db_path: Path | None = None
    full: bool = False


class ImportResult(BaseModel):
    source: str
    sessions_seen: int
    sessions_written: int
    events_seen: int
    events_written: int
    files_written: int
    checkpoint_updated: bool


def import_history(request: ImportRequest, repository: ImportRepository) -> ImportResult:
    ...
```

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
- The command handler may run import before search based on command flags.
- Call search with the user query, filters, and search repository.
- Search reads indexed ctx history.
- Return cited results with follow-up commands.

Search itself does not trigger import. Import-before-search is command
orchestration, not search behavior.

### Search Interface

```python
from pydantic import BaseModel


class SearchRequest(BaseModel):
    query: str
    session_id: str | None = None
    workspace: str | None = None
    file: str | None = None
    since: str | None = None
    include_subagents: bool = False
    limit: int = 50


class SearchResult(BaseModel):
    session_id: str
    event_id: str
    event_type: str
    time_created: int | None = None
    title: str | None = None
    workspace: str | None = None
    source_path: str | None = None
    snippet: str
    citation: str
    follow_up: str


def search_history(request: SearchRequest, repository: SearchRepository) -> list[SearchResult]:
    ...
```

## Show Workflow

`ocint ctx show session` and `ocint ctx show event` read imported ctx history and
render transcript context.

The workflow is:

- Resolve and open the ctx database.
- Load the requested session or event through the show repository.
- For events, load neighboring session events.
- Render text, markdown, or JSON.

### Show Interface

```python
from pydantic import BaseModel


class ShowSessionRequest(BaseModel):
    session_id: str


class ShowEventRequest(BaseModel):
    event_id: str
    window: int = 5


def show_session(request: ShowSessionRequest, repository: ShowRepository) -> CtxTranscript:
    ...


def show_event(request: ShowEventRequest, repository: ShowRepository) -> CtxEventContext:
    ...
```

## Locate Workflow

`ocint ctx locate session` and `ocint ctx locate event` return provenance for
imported ctx history.

The workflow is:

- Resolve and open the ctx database.
- Load source, session, and event metadata through the locate repository.
- Return provider, source path, source table, native IDs, and citation data.

### Locate Interface

```python
from pydantic import BaseModel


class LocateSessionRequest(BaseModel):
    session_id: str


class LocateEventRequest(BaseModel):
    event_id: str


def locate_session(request: LocateSessionRequest, repository: LocateRepository) -> CtxLocateResult:
    ...


def locate_event(request: LocateEventRequest, repository: LocateRepository) -> CtxLocateResult:
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
from typing import Any

from pydantic import BaseModel


class SqlRequest(BaseModel):
    sql: str


def query_sql(request: SqlRequest, repository: SqlRepository) -> list[dict[str, Any]]:
    ...
```
