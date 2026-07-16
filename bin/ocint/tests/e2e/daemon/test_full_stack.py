import asyncio
import hashlib
import hmac
import json
import socket
import subprocess
import time
from collections.abc import Mapping
from functools import partial
from pathlib import Path

import httpx
import pytest
from aiohttp import web
from ocint.daemon.api import ControlApiResources, create_control_app
from ocint.daemon.channels import SlackChannel
from ocint.daemon.config import (
    ApiConfig,
    ChannelsConfig,
    DaemonConfig,
    DaemonSettings,
    LoadedDaemonConfig,
    OpenCodeConfig,
    ProviderConfig,
    RepositoryConfig,
    SchedulerConfig,
)
from ocint.daemon.db import create_daemon_engine, migrate_daemon_db
from ocint.daemon.git import GitHubPublisher, ManagedCommand, RepositoryManager
from ocint.daemon.models import JobState
from ocint.daemon.outbox_repository import OutboxRepository
from ocint.daemon.repository import ControlRepository
from ocint.daemon.run import ActiveConfig, DaemonRunner
from ocint.daemon.runner_repository import RunnerRepository
from ocint.daemon.runtime import OpenCodeRuntime
from ocint.daemon.service import accept_work
from ocint.daemon.workspace_repository import WorkspaceRepository
from pydantic import HttpUrl, SecretStr


@pytest.mark.asyncio
async def test_real_control_stack_retries_publication_without_reexecuting_and_deduplicates(tmp_path: Path) -> None:
    # GIVEN stateful fake OpenCode, GitHub, and Slack providers plus a real bare Git remote
    provider_state: list[str] = []
    sessions: list[Mapping[str, str]] = []
    prompts: list[str] = []
    pull_requests: list[Mapping[str, str | int]] = []
    slack_messages: list[str] = []
    slack_delivery_ids: set[str] = set()
    prompt_received = asyncio.Event()
    subscription_ready = asyncio.Event()
    pull_started = asyncio.Event()

    async def health(_request: web.Request) -> web.Response:
        return web.json_response({"healthy": True, "version": "1.17.20"})

    async def list_sessions(_request: web.Request) -> web.Response:
        return web.json_response(sessions)

    async def create_session(request: web.Request) -> web.Response:
        payload = await request.json()
        session = {"id": "ses_full", "title": payload["title"]}
        sessions.append(session)
        return web.json_response(session, status=201)

    async def messages(_request: web.Request) -> web.Response:
        if not prompts:
            return web.json_response([])
        return web.json_response(
            [
                {
                    "info": {"id": "msg-user", "role": "user"},
                    "parts": [{"type": "text", "text": prompts[-1]}],
                },
                {
                    "info": {"id": "msg-full", "role": "assistant"},
                    "parts": [{"type": "tool", "text": "edited"}],
                },
            ]
        )

    async def prompt(request: web.Request) -> web.Response:
        assert subscription_ready.is_set()
        payload = await request.json()
        prompts.append(payload["parts"][0]["text"])
        directory = Path(request.headers["x-opencode-directory"])
        rendered = "deterministic daemon change\n" if len(prompts) == 1 else "continued daemon change\n"
        (directory / "daemon-e2e.txt").write_text(rendered)
        prompt_received.set()
        return web.json_response({"message": "connection dropped after acceptance"}, status=503)

    async def events(request: web.Request) -> web.StreamResponse:
        response = web.StreamResponse(headers={"Content-Type": "text/event-stream"})
        await response.prepare(request)
        connected = {
            "payload": {"type": "server.connected", "properties": {}},
        }
        await response.write(f"data: {json.dumps(connected)}\n\n".encode())
        subscription_ready.set()
        await prompt_received.wait()
        await response.write_eof()
        return response

    async def status(_request: web.Request) -> web.Response:
        return web.json_response({"ses_full": {"type": "idle"}})

    async def abort(_request: web.Request) -> web.Response:
        provider_state.append("aborted")
        return web.json_response(True)

    async def list_pulls(_request: web.Request) -> web.Response:
        return web.json_response(pull_requests)

    async def create_pull(request: web.Request) -> web.Response:
        provider_state.append("pull-attempt")
        if provider_state.count("pull-attempt") == 1:
            pull_started.set()
            await asyncio.sleep(5)
            return web.json_response({"message": "first runner disappeared"}, status=503)
        payload = await request.json()
        pull = {"html_url": "http://provider.local/pulls/1", "number": 1, "head": payload["head"]}
        pull_requests.append(pull)
        return web.json_response(pull, status=201)

    async def slack_post(request: web.Request) -> web.Response:
        payload = await request.json()
        delivery_id = payload["client_msg_id"]
        if delivery_id in slack_delivery_ids:
            return web.json_response({"ok": True, "ts": "2.1"})
        if payload["text"] == "job completed":
            provider_state.append("notification-attempt")
            if provider_state.count("notification-attempt") == 1:
                return web.json_response({"ok": False}, status=503)
        slack_delivery_ids.add(delivery_id)
        slack_messages.append(payload["text"])
        return web.json_response({"ok": True, "ts": "2.1"})

    provider = web.Application()
    provider.add_routes(
        [
            web.get("/global/health", health),
            web.get("/global/event", events),
            web.get("/session", list_sessions),
            web.post("/session", create_session),
            web.get("/session/{session_id}/message", messages),
            web.post("/session/{session_id}/prompt_async", prompt),
            web.get("/session/status", status),
            web.post("/session/{session_id}/abort", abort),
            web.get("/repos/owner/repo/pulls", list_pulls),
            web.post("/repos/owner/repo/pulls", create_pull),
            web.post("/chat.postMessage", slack_post),
        ]
    )
    provider_runner = web.AppRunner(provider)
    await provider_runner.setup()
    provider_listener = socket.socket()
    provider_listener.bind(("127.0.0.1", 0))
    provider_listener.listen()
    await web.SockSite(provider_runner, provider_listener).start()
    provider_url = f"http://127.0.0.1:{provider_listener.getsockname()[1]}"

    source = tmp_path / "source"
    remote = tmp_path / "remote.git"
    source.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=source, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Daemon Test"], cwd=source, check=True)
    subprocess.run(["git", "config", "user.email", "daemon@example.test"], cwd=source, check=True)
    (source / "README.md").write_text("seed\n")
    subprocess.run(["git", "add", "README.md"], cwd=source, check=True)
    subprocess.run(["git", "commit", "-m", "seed"], cwd=source, check=True, capture_output=True)
    subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True)
    subprocess.run(["git", "remote", "add", "origin", str(remote)], cwd=source, check=True)
    subprocess.run(["git", "push", "origin", "main"], cwd=source, check=True, capture_output=True)

    config = DaemonConfig(
        database_path=tmp_path / "control.sqlite",
        mirror_root=tmp_path / "mirrors",
        worktree_root=tmp_path / "worktrees",
        repositories=[
            RepositoryConfig(
                name="repo",
                remote_url=str(remote),
                github_repository="owner/repo",
                actors=frozenset(["U1"]),
                checks=[["python3", "-c", "from pathlib import Path; assert Path('daemon-e2e.txt').is_file()"]],
            )
        ],
        scheduler=SchedulerConfig(
            capacity=1,
            lease_seconds=10,
            heartbeat_seconds=1,
            max_attempts=3,
            poll_seconds=0.05,
            job_timeout_seconds=10,
            shutdown_timeout_seconds=2,
            command_timeout_seconds=10,
        ),
        opencode=OpenCodeConfig(server_url=HttpUrl(provider_url), request_timeout_seconds=5),
        api=ApiConfig(port=8732),
        providers=ProviderConfig(
            github_api_url=HttpUrl(provider_url),
            slack_api_url=HttpUrl(provider_url),
            slack_socket_url=HttpUrl(provider_url),
        ),
        channels=ChannelsConfig(),
    )
    settings = DaemonSettings(
        config=tmp_path / "daemon.toml",
        api_token=SecretStr("api-token"),
        github_token=SecretStr("github-token"),
    )
    loaded = LoadedDaemonConfig(path=tmp_path / "daemon.toml", config=config, settings=settings)
    migrate_daemon_db(config.database_path)
    engine = create_daemon_engine(config.database_path)
    repository = ControlRepository(engine)
    environment = {
        "PATH": "/usr/local/bin:/usr/bin:/bin",
        "LANG": "C.UTF-8",
        "HOME": str(tmp_path),
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_AUTHOR_NAME": "Daemon Test",
        "GIT_AUTHOR_EMAIL": "daemon@example.test",
        "GIT_COMMITTER_NAME": "Daemon Test",
        "GIT_COMMITTER_EMAIL": "daemon@example.test",
    }
    manager = RepositoryManager(
        config.mirror_root,
        config.worktree_root,
        ManagedCommand(10, 65536, frozenset(["api-token", "github-token"])),
        {"PATH": environment["PATH"], "LANG": environment["LANG"], "CI": "1"},
        environment,
    )
    runtime = OpenCodeRuntime(provider_url, "opencode", "", 5)
    await runtime.start()
    await runtime.health()
    channel = SlackChannel(
        provider_url,
        "slack-token",
        "signing-secret",
        {"C1": "repo"},
        partial(accept_work, config=config, repository=repository),
    )
    active = ActiveConfig(loaded, tmp_path)
    daemon = DaemonRunner(
        active,
        repository,
        manager,
        runtime,
        GitHubPublisher(provider_url, "github-token"),
        [channel],
        OutboxRepository(engine),
        RunnerRepository(engine, repository),
        WorkspaceRepository(engine),
    )
    control = create_control_app(
        ControlApiResources(
            repository=repository,
            config_provider=active.current,
            reload_config=active.reload,
            token="api-token",
            slack_channels=[channel],
            runtime=runtime,
        )
    )
    control_client = httpx.AsyncClient(transport=httpx.ASGITransport(app=control), base_url="http://control")
    daemon_task = asyncio.create_task(daemon.run())

    # WHEN a signed Slack delivery is duplicated and GitHub transiently fails
    timestamp = str(int(time.time()))
    body = json.dumps(
        {
            "event_id": "Ev-full",
            "team_id": "T1",
            "event": {"channel": "C1", "user": "U1", "text": "make deterministic change", "ts": "1.2"},
        }
    ).encode()
    digest = hmac.new(b"signing-secret", b"v0:" + timestamp.encode() + b":" + body, hashlib.sha256).hexdigest()
    slack_headers = {"X-Slack-Request-Timestamp": timestamp, "X-Slack-Signature": f"v0={digest}"}
    api_headers = {"Authorization": "Bearer api-token"}
    async with control_client as client:
        response = await client.get("/?token=api-token")
        assert response.status_code == 200
        response = await client.get("/api/jobs")
        assert response.status_code == 200
        for _delivery in range(2):
            response = await client.post("/api/slack/events", content=body, headers=slack_headers)
            assert response.status_code == 200
        primary_id = repository.list()[0].id
        await pull_started.wait()
        second_body = json.dumps(
            {
                "event_id": "Ev-second",
                "team_id": "T1",
                "event": {"channel": "C1", "user": "U1", "text": "must remain queued", "ts": "1.3"},
            }
        ).encode()
        second_digest = hmac.new(
            b"signing-secret",
            b"v0:" + timestamp.encode() + b":" + second_body,
            hashlib.sha256,
        ).hexdigest()
        response = await client.post(
            "/api/slack/events",
            content=second_body,
            headers={"X-Slack-Request-Timestamp": timestamp, "X-Slack-Signature": f"v0={second_digest}"},
        )
        assert response.status_code == 200
        restarted = DaemonRunner(
            active,
            repository,
            manager,
            runtime,
            GitHubPublisher(provider_url, "github-token"),
            [channel],
            OutboxRepository(engine),
            RunnerRepository(engine, repository),
            WorkspaceRepository(engine),
        )
        restarted_task = asyncio.create_task(restarted.run())
        await asyncio.sleep(0.1)
        assert prompts == ["make deterministic change"]
        secondary = next(item for item in repository.list() if item.id != primary_id)
        assert secondary.state is JobState.QUEUED
        response = await client.post(f"/api/jobs/{secondary.id}/cancel", headers=api_headers)
        assert response.status_code == 202
        daemon_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await daemon_task
        deadline = asyncio.get_running_loop().time() + 20
        completed = False
        while asyncio.get_running_loop().time() < deadline:
            response = await client.get("/api/jobs", headers=api_headers)
            jobs = response.json()
            primary_response = next((item for item in jobs if item["id"] == primary_id), None)
            if primary_response is not None and primary_response["state"] == "completed":
                completed = True
                break
            await asyncio.sleep(0.1)
        assert completed
        response = await client.get(f"/api/jobs/{primary_id}/events?after=0")
        replay = response.json()
        assert response.status_code == 200
        assert replay

    # THEN execution happened once, publication resumed at its checkpoint, and one durable job/outbox result exists
    assert repository.get(primary_id).state.value == "completed"
    await asyncio.sleep(2.2)
    assert len(repository.list()) == 2
    assert prompts == ["make deterministic change"]
    assert provider_state.count("pull-attempt") == 2
    assert provider_state.count("notification-attempt") == 2
    assert len(pull_requests) == 1
    assert len(slack_messages) == 4
    assert sum(message.endswith("accepted") for message in slack_messages) == 2
    assert "cancelled" in slack_messages
    assert "job completed" in slack_messages
    completed_job = repository.get(primary_id)
    assert completed_job.attempt_count == 3
    assert completed_job.commit_sha
    assert completed_job.pushed
    assert completed_job.pull_request_url == "http://provider.local/pulls/1"
    assert len(repository.artifacts(completed_job.id)) == 2
    assert {item.kind for item in repository.events(completed_job.id)} >= {
        "server.connected",
    }
    branch = subprocess.run(
        ["git", "--git-dir", str(remote), "rev-parse", f"refs/heads/{completed_job.branch}"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert branch == completed_job.commit_sha

    restarted.stopping.set()
    await restarted_task
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=control), base_url="http://control") as client:
        response = await client.get(f"/api/jobs/{completed_job.id}/session/messages", headers=api_headers)
        session_messages = response.json()
        assert response.status_code == 200
        assert [message["role"] for message in session_messages] == ["user", "assistant"]
        response = await client.post(
            f"/api/jobs/{completed_job.id}/follow-up",
            json={"text": "continue in retained session", "idempotency_key": "follow-up-1"},
            headers=api_headers,
        )
        follow_up = response.json()
        assert response.status_code == 202
    continued = repository.get(follow_up["id"])
    assert continued.parent_job_id == completed_job.id
    assert continued.worktree_path == completed_job.worktree_path
    assert continued.branch == completed_job.branch
    assert continued.session_id == completed_job.session_id
    prompt_received.clear()
    subscription_ready.clear()
    continuation_runner = DaemonRunner(
        active,
        repository,
        manager,
        runtime,
        GitHubPublisher(provider_url, "github-token"),
        [channel],
        OutboxRepository(engine),
        RunnerRepository(engine, repository),
        WorkspaceRepository(engine),
    )
    continuation_task = asyncio.create_task(continuation_runner.run())
    deadline = asyncio.get_running_loop().time() + 20
    while asyncio.get_running_loop().time() < deadline:
        continued = repository.get(continued.id)
        if continued.state.value == "completed":
            break
        await asyncio.sleep(0.1)
    assert continued.state.value == "completed"
    assert len(sessions) == 1
    assert prompts == ["make deterministic change", "continue in retained session"]
    continuation_runner.stopping.set()
    await continuation_task
    await runtime.close()
    await provider_runner.cleanup()
    engine.dispose()
