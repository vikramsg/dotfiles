import hashlib
import hmac
import json
import time
from functools import partial
from pathlib import Path

import httpx
import pytest
from ocint.daemon.api import ControlApiResources, create_control_app
from ocint.daemon.channels import SlackChannel
from ocint.daemon.config import DaemonConfig, DaemonSettings, LoadedDaemonConfig, RepositoryConfig
from ocint.daemon.db import create_daemon_engine, migrate_daemon_db
from ocint.daemon.repository import ControlRepository
from ocint.daemon.run import ActiveConfig
from ocint.daemon.runtime import OpenCodeRuntime
from ocint.daemon.service import accept_work


@pytest.mark.asyncio
async def test_slack_http_does_not_acknowledge_failed_durable_submission(tmp_path: Path) -> None:
    # GIVEN authenticated Slack ingress whose injected durable submission fails
    path = tmp_path / "control.sqlite"
    migrate_daemon_db(path)
    engine = create_daemon_engine(path)
    repository = ControlRepository(engine)
    config = DaemonConfig(
        database_path=path,
        mirror_root=tmp_path / "mirrors",
        worktree_root=tmp_path / "worktrees",
        repositories=[RepositoryConfig(name="repo", remote_url="file:///remote", actors=frozenset(["U1"]))],
    )
    settings = DaemonSettings(config=tmp_path / "daemon.toml")
    active = ActiveConfig(LoadedDaemonConfig(path=tmp_path / "daemon.toml", config=config, settings=settings), tmp_path)
    failing_repository = ControlRepository(create_daemon_engine(tmp_path / "missing-parent" / "control.sqlite"))
    channel = SlackChannel(
        "http://127.0.0.1",
        "token",
        "signing-secret",
        {"C1": "repo"},
        partial(accept_work, config=config, repository=failing_repository),
    )
    app = create_control_app(
        ControlApiResources(
            repository=repository,
            config_provider=active.current,
            reload_config=active.reload,
            token="api-token",
            slack_channels=[channel],
            runtime=OpenCodeRuntime("http://127.0.0.1", "", "", 1),
        )
    )
    timestamp = str(int(time.time()))
    body = json.dumps(
        {
            "event_id": "Ev-fail",
            "team_id": "T1",
            "event": {"channel": "C1", "user": "U1", "text": "fix", "ts": "1.2"},
        }
    ).encode()
    digest = hmac.new(b"signing-secret", b"v0:" + timestamp.encode() + b":" + body, hashlib.sha256).hexdigest()

    # WHEN Slack posts the correctly signed event
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://control") as client:
        response = await client.post(
            "/api/slack/events",
            content=body,
            headers={"X-Slack-Request-Timestamp": timestamp, "X-Slack-Signature": f"v0={digest}"},
        )

    # THEN persistence failure prevents a success acknowledgement and no job exists
    assert response.status_code == 503
    assert repository.list() == []
    engine.dispose()
