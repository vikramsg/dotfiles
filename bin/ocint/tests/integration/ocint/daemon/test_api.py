from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from ocint.daemon.api import create_api_router
from ocint.daemon.db import create_daemon_engine
from ocint.daemon.db.schema import metadata
from ocint.daemon.models import GitHubLogin, GitRepository
from ocint.daemon.pull_request_job.config import PullRequestJobConfig, RepositoryPolicy, SchedulerPolicy
from ocint.daemon.pull_request_job.models import (
    PullRequestJob,
    PullRequestJobRequest,
    SessionCheckpoint,
    WorktreeCheckpoint,
)
from ocint.daemon.pull_request_job.repository import PullRequestJobRepository
from ocint.daemon.pull_request_job.service import authorize


class FakeOpenCodeConnection:
    server_url = "http://127.0.0.1:4097"
    username = "opencode"
    password = "ephemeral-password"


@pytest.mark.asyncio
async def test_api_cannot_forge_internal_source_authorization(tmp_path: Path) -> None:
    # GIVEN
    engine = create_daemon_engine(tmp_path / "control.sqlite")
    metadata.create_all(engine)
    repository = PullRequestJobRepository(engine)
    config = PullRequestJobConfig(
        repositories=(
            RepositoryPolicy(
                git_repository=GitRepository(name="repo", remote_url="git@example.test:repo.git"),
                github_repository="owner/repo",
                author_name="Agent",
                author_email="agent@example.test",
                actors=frozenset((GitHubLogin("maintainer"),)),
                checks=(),
            ),
        ),
        scheduler=SchedulerPolicy(capacity=1, job_timeout_seconds=60, shutdown_timeout_seconds=10),
    )

    def submit(request: PullRequestJobRequest) -> PullRequestJob:
        authorize(request, config)
        return repository.submit(request)

    app = FastAPI()
    app.include_router(create_api_router(repository, submit, "secret", FakeOpenCodeConnection()))
    payload = {
        "idempotency_key": "forged",
        "actor": "slack:u1",
        "repository": "repo",
        "title": "Work title",
        "prompt": "work",
        "authorization": "source_verified",
    }

    # WHEN
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://daemon.test") as client:
        forged = await client.post("/api/jobs", headers={"Authorization": "Bearer secret"}, json=payload)
        denied = await client.post(
            "/api/jobs",
            headers={"Authorization": "Bearer secret"},
            json={key: value for key, value in payload.items() if key != "authorization"},
        )

    # THEN
    assert forged.status_code == 422
    assert denied.status_code == 403
    assert repository.list() == []
    engine.dispose()


@pytest.mark.asyncio
async def test_api_protects_jobs_and_live_attachment_with_bearer_authentication(tmp_path: Path) -> None:
    # GIVEN
    engine = create_daemon_engine(tmp_path / "control.sqlite")
    metadata.create_all(engine)
    repository = PullRequestJobRepository(engine)
    app = FastAPI()
    app.include_router(create_api_router(repository, repository.submit, "secret", FakeOpenCodeConnection()))

    # WHEN
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://daemon.test") as client:
        denied = await client.get("/health")
        headers = {"Authorization": "Bearer secret"}
        health = await client.get("/health", headers=headers)
        submitted = await client.post(
            "/api/jobs",
            headers=headers,
            json={
                "idempotency_key": "key",
                "actor": "actor",
                "repository": "repo",
                "title": "Work title",
                "prompt": "work",
            },
        )
        job_id = submitted.json()["id"]
        repository.checkpoint(
            job_id,
            WorktreeCheckpoint(path=tmp_path / "worktree", branch=f"ocint/{job_id}", base_revision="base"),
        )
        repository.checkpoint(
            job_id,
            SessionCheckpoint(session_id="session", server_url=FakeOpenCodeConnection.server_url),
        )
        repository.claim(job_id)
        listed = await client.get("/api/jobs", headers=headers)
        job_status = await client.get(f"/api/jobs/{job_id}", headers=headers)
        denied_attach = await client.get(f"/api/jobs/{job_id}/attach")
        attachment = await client.get(f"/api/jobs/{job_id}/attach", headers=headers)
        removed = await client.get("/", headers=headers)

    # THEN
    assert denied.status_code == 401
    assert health.json() == {"status": "ready"}
    assert submitted.status_code == 202
    assert submitted.json()["title"] == "ocint: Work title"
    assert listed.json() == [job_status.json()]
    assert "password" not in job_status.json()
    assert denied_attach.status_code == 401
    assert attachment.json() == {
        "server_url": "http://127.0.0.1:4097",
        "username": "opencode",
        "password": "ephemeral-password",
        "directory": str(tmp_path / "worktree"),
        "session_id": "session",
    }
    assert removed.status_code == 404
    engine.dispose()
