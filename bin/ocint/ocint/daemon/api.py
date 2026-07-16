import asyncio
import hmac
import html
import json
from collections.abc import AsyncIterator, Callable
from typing import Annotated

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request, Response, status
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ocint.daemon.channels import SlackChannel
from ocint.daemon.config import LoadedDaemonConfig
from ocint.daemon.models import Artifact, Job, PersistedEvent, RuntimeMessage, WorkRequest
from ocint.daemon.repository import ControlRepository
from ocint.daemon.runtime import OpenCodeRuntime
from ocint.daemon.service import accept_work, attach_command, build_follow_up, cancel_job, retry_job


class FollowUpRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    text: str = Field(min_length=1)
    idempotency_key: str = ""


class HealthResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: str


class SlackIngressResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    ok: bool


class ReloadResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: str


class JobResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    state: str
    stage: str
    repository: str
    conversation_id: str
    parent_job_id: str
    workspace_owner_id: str
    attempt_count: int
    session_id: str
    worktree_path: str
    base_revision: str
    server_url: str
    attach_command: str
    error: str
    cancel_requested: bool
    artifacts: list[Artifact]
    origin: WorkRequest
    created_at: str
    updated_at: str


class ControlApiResources(BaseModel):
    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    repository: ControlRepository
    config_provider: Callable[[], LoadedDaemonConfig]
    reload_config: Callable[[], LoadedDaemonConfig]
    token: str
    slack_channels: list[SlackChannel]
    runtime: OpenCodeRuntime


def create_control_app(resources: ControlApiResources) -> FastAPI:
    app = FastAPI(title="ocint daemon", docs_url=None, redoc_url=None)
    app.include_router(create_api_router(resources))
    return app


def create_api_router(resources: ControlApiResources) -> APIRouter:
    router = APIRouter()

    async def authenticate(request: Request) -> str:
        supplied = request.headers.get("Authorization", "").removeprefix("Bearer ")
        supplied = supplied or request.cookies.get("ocint_token", "") or request.query_params.get("token", "")
        if not supplied or not hmac.compare_digest(supplied, resources.token):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Supply Authorization: Bearer TOKEN or open /?token=TOKEN once.",
            )
        return supplied

    authenticated = Annotated[str, Depends(authenticate)]

    @router.get("/health", response_model=HealthResponse)
    async def health(_authenticated: authenticated) -> HealthResponse:
        return HealthResponse(status="ready")

    @router.get("/api/jobs", response_model=list[JobResponse])
    async def jobs(_authenticated: authenticated) -> list[JobResponse]:
        return [_job_response(resources.repository, item) for item in resources.repository.list()]

    @router.get("/api/jobs/{job_id}", response_model=JobResponse)
    async def job(job_id: str, _authenticated: authenticated) -> JobResponse:
        return _job_response(resources.repository, _job_or_404(resources.repository, job_id))

    @router.post("/api/jobs", response_model=JobResponse, status_code=status.HTTP_202_ACCEPTED)
    async def submit(work: WorkRequest, _authenticated: authenticated) -> JobResponse:
        try:
            item = accept_work(work, resources.config_provider().config, resources.repository)
        except PermissionError as error:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(error)) from error
        except ValueError as error:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)) from error
        return _job_response(resources.repository, item)

    @router.get("/api/jobs/{job_id}/events", response_model=list[PersistedEvent])
    async def events(job_id: str, after: int = 0, _authenticated: authenticated = "") -> list[PersistedEvent]:
        _job_or_404(resources.repository, job_id)
        return resources.repository.events(job_id, after)

    @router.get("/api/jobs/{job_id}/stream")
    async def stream(job_id: str, request: Request, _authenticated: authenticated) -> StreamingResponse:
        _job_or_404(resources.repository, job_id)
        cursor = int(request.headers.get("Last-Event-ID", request.query_params.get("after", "0")))

        async def replay() -> AsyncIterator[bytes]:
            current = cursor
            while True:
                if await request.is_disconnected():
                    return
                for item in resources.repository.events(job_id, current):
                    current = item.id
                    payload = json.dumps(item.model_dump(mode="json"))
                    yield f"id: {item.id}\ndata: {payload}\n\n".encode()
                await asyncio.sleep(0.5)

        return StreamingResponse(replay(), media_type="text/event-stream", headers={"Cache-Control": "no-store"})

    @router.get("/api/jobs/{job_id}/session/messages", response_model=list[RuntimeMessage])
    async def session_messages(job_id: str, _authenticated: authenticated) -> list[RuntimeMessage]:
        current = _job_or_404(resources.repository, job_id)
        if current.worktree_path is None or not current.session_id:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="job has no retained OpenCode session")
        return await resources.runtime.messages(current.worktree_path, current.session_id)

    @router.get("/api/jobs/{job_id}/session/activity", response_model=list[PersistedEvent])
    async def session_activity(job_id: str, _authenticated: authenticated) -> list[PersistedEvent]:
        _job_or_404(resources.repository, job_id)
        return [
            item
            for item in resources.repository.events(job_id)
            if "tool" in item.kind or item.kind.startswith("message.") or item.kind == "session.status"
        ]

    @router.post("/api/jobs/{job_id}/follow-up", response_model=JobResponse, status_code=status.HTTP_202_ACCEPTED)
    async def follow_up(job_id: str, payload: FollowUpRequest, _authenticated: authenticated) -> JobResponse:
        try:
            current = _job_or_404(resources.repository, job_id)
            request = build_follow_up(current, payload.text, payload.idempotency_key)
            item = accept_work(request, resources.config_provider().config, resources.repository)
        except (ValueError, ValidationError) as error:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)) from error
        return _job_response(resources.repository, item)

    @router.post("/api/jobs/{job_id}/cancel", response_model=JobResponse, status_code=status.HTTP_202_ACCEPTED)
    async def cancel(job_id: str, _authenticated: authenticated) -> JobResponse:
        return _job_response(resources.repository, cancel_job(resources.repository, job_id))

    @router.post("/api/jobs/{job_id}/retry", response_model=JobResponse, status_code=status.HTTP_202_ACCEPTED)
    async def retry(job_id: str, _authenticated: authenticated) -> JobResponse:
        try:
            item = retry_job(resources.repository, job_id)
        except ValueError as error:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
        resources.repository.record_control_event(item.id, "control.retry", "{}")
        return _job_response(resources.repository, item)

    @router.post("/api/reload", response_model=ReloadResponse)
    async def reload(_authenticated: authenticated) -> ReloadResponse:
        try:
            resources.reload_config()
        except Exception as error:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail=f"configuration unchanged: {error}"
            ) from error
        return ReloadResponse(status="reloaded")

    @router.post("/api/slack/events", response_model=SlackIngressResponse)
    async def slack_event(request: Request) -> SlackIngressResponse:
        if not resources.slack_channels:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Slack HTTP ingress is disabled")
        body = await request.body()
        try:
            resources.slack_channels[0].submit_signed(
                request.headers.get("X-Slack-Request-Timestamp", ""),
                request.headers.get("X-Slack-Signature", ""),
                body,
            )
        except ValueError as error:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(error)) from error
        except Exception as error:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="durable submission failed"
            ) from error
        return SlackIngressResponse(ok=True)

    @router.get("/", response_class=HTMLResponse)
    async def frontend(request: Request, _authenticated: authenticated) -> Response:
        response = HTMLResponse(_frontend(resources.repository.list()))
        if request.query_params.get("token"):
            response.set_cookie("ocint_token", resources.token, httponly=True, samesite="strict", path="/")
        return response

    return router


def _job_or_404(repository: ControlRepository, job_id: str) -> Job:
    try:
        return repository.get(job_id)
    except Exception as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="job not found") from error


def _job_response(repository: ControlRepository, item: Job) -> JobResponse:
    return JobResponse(
        id=item.id,
        state=item.state.value,
        stage=item.stage.value,
        repository=item.repository,
        conversation_id=item.conversation_id,
        parent_job_id=item.parent_job_id,
        workspace_owner_id=item.workspace_owner_id,
        attempt_count=item.attempt_count,
        session_id=item.session_id,
        worktree_path=str(item.worktree_path or ""),
        base_revision=item.base_revision,
        server_url=item.server_url,
        attach_command=attach_command(item),
        error=item.error,
        cancel_requested=item.cancel_requested,
        artifacts=repository.artifacts(item.id),
        origin=repository.origin(item.id),
        created_at=item.created_at.isoformat(),
        updated_at=item.updated_at.isoformat(),
    )


def _frontend(jobs: list[Job]) -> str:
    rows = "".join(
        "<tr>"
        f"<td><a href='/api/jobs/{html.escape(item.id)}'>{html.escape(item.id)}</a></td>"
        f"<td>{html.escape(item.state.value)}</td><td>{html.escape(item.stage.value)}</td>"
        f"<td>{html.escape(item.session_id)}</td><td>{html.escape(str(item.worktree_path or ''))}</td>"
        f"<td>{html.escape(item.server_url)}</td><td><code>{html.escape(attach_command(item))}</code></td>"
        f"<td><button onclick=\"fetch('/api/jobs/{item.id}/cancel',{{method:'POST'}})\">Cancel</button>"
        f"<button onclick=\"fetch('/api/jobs/{item.id}/retry',{{method:'POST'}})\">Retry</button></td>"
        f"<td><input id='follow-{item.id}' aria-label='Follow-up prompt'>"
        f"<button onclick=\"fetch('/api/jobs/{item.id}/follow-up',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{text:document.getElementById('follow-{item.id}').value}})}})\">Send</button></td>"
        f"<td><a href='/api/jobs/{item.id}/session/messages'>Messages</a> "
        f"<a href='/api/jobs/{item.id}/session/activity'>Tools</a></td>"
        "</tr>"
        for item in jobs
    )
    return (
        "<!doctype html><html><head><title>ocint daemon</title></head><body>"
        "<h1>ocint daemon jobs</h1><table><thead><tr><th>Job</th><th>Status</th><th>Stage</th>"
        "<th>Session ID</th><th>Worktree</th><th>Server URL</th><th>Attach command</th><th>Actions</th>"
        f"<th>Follow-up</th><th>Session</th></tr></thead><tbody>{rows}</tbody></table></body></html>"
    )
