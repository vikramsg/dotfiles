import builtins
import hmac
from collections.abc import Callable
from typing import Annotated, Protocol

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict

from ocint.daemon.models import Job, JobState, OpenCodeAttachment, WorkRequest


class HealthResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    status: str


class JobResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    id: str
    state: str
    stage: str
    repository: str
    session_id: str
    worktree_path: str
    commit_sha: str
    pull_request_url: str
    error: str


class JobQueries(Protocol):
    def get(self, job_id: str) -> Job: ...
    def list(self, limit: int = 100) -> builtins.list[Job]: ...


class OpenCodeConnection(Protocol):
    server_url: str
    username: str
    password: str


def create_api_router(
    queries: JobQueries,
    submit: Callable[[WorkRequest], Job],
    token: str,
    opencode: OpenCodeConnection,
) -> APIRouter:
    router = APIRouter()

    async def authenticate(request: Request) -> str:
        authorization = request.headers.get("Authorization", "")
        supplied = authorization.removeprefix("Bearer ") if authorization.startswith("Bearer ") else ""
        if not supplied or not hmac.compare_digest(supplied, token):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Supply Authorization: Bearer TOKEN")
        return supplied

    authenticated = Annotated[str, Depends(authenticate)]

    @router.get("/health", response_model=HealthResponse)
    async def health(_authenticated: authenticated) -> HealthResponse:
        return HealthResponse(status="ready")

    @router.post("/api/jobs", response_model=JobResponse, status_code=status.HTTP_202_ACCEPTED)
    async def submit_job(work: WorkRequest, _authenticated: authenticated) -> JobResponse:
        try:
            return response(submit(work))
        except PermissionError as error:
            raise HTTPException(status_code=403, detail=str(error)) from error
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

    @router.get("/api/jobs", response_model=list[JobResponse])
    async def jobs(_authenticated: authenticated) -> list[JobResponse]:
        return [response(item) for item in queries.list()]

    @router.get("/api/jobs/{job_id}", response_model=JobResponse)
    async def job_status(job_id: str, _authenticated: authenticated) -> JobResponse:
        try:
            return response(queries.get(job_id))
        except Exception as error:
            raise HTTPException(status_code=404, detail="job not found") from error

    @router.get("/api/jobs/{job_id}/attach", response_model=OpenCodeAttachment)
    async def attach(job_id: str, _authenticated: authenticated) -> OpenCodeAttachment:
        try:
            item = queries.get(job_id)
        except Exception as error:
            raise HTTPException(status_code=404, detail="job not found") from error
        if (
            item.state is not JobState.RUNNING
            or not item.session_id
            or item.worktree_path is None
            or item.server_url != opencode.server_url
        ):
            raise HTTPException(status_code=409, detail="job does not have a running OpenCode session")
        return OpenCodeAttachment(
            server_url=opencode.server_url,
            username=opencode.username,
            password=opencode.password,
            directory=str(item.worktree_path),
            session_id=item.session_id,
        )

    return router


def response(item: Job) -> JobResponse:
    return JobResponse(
        id=item.id,
        state=item.state.value,
        stage=item.stage.value,
        repository=item.repository,
        session_id=item.session_id,
        worktree_path=str(item.worktree_path or ""),
        commit_sha=item.commit_sha,
        pull_request_url=item.pull_request_url,
        error=item.error,
    )
