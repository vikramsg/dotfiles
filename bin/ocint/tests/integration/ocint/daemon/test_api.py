from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from ocint.daemon.api import create_api_router
from ocint.daemon.db import create_daemon_engine
from ocint.daemon.db.schema import metadata
from ocint.daemon.repository import ControlRepository


@pytest.mark.asyncio
async def test_api_requires_bearer_and_supports_submit_list_status(tmp_path: Path) -> None:
    # GIVEN
    engine = create_daemon_engine(tmp_path / "control.sqlite")
    metadata.create_all(engine)
    repository = ControlRepository(engine)
    app = FastAPI()
    app.include_router(create_api_router(repository, repository.submit, "secret"))

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
        listed = await client.get("/api/jobs", headers=headers)
        job_status = await client.get(f"/api/jobs/{submitted.json()['id']}", headers=headers)
        removed = await client.get("/", headers=headers)

    # THEN
    assert denied.status_code == 401
    assert health.json() == {"status": "ready"}
    assert submitted.status_code == 202
    assert submitted.json()["title"] == "ocint: Work title"
    assert listed.json() == [job_status.json()]
    assert removed.status_code == 404
    engine.dispose()
