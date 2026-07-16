import asyncio
import json
import socket
import subprocess
from collections.abc import Mapping
from pathlib import Path

import pytest
from aiohttp import web
from ocint.daemon.channels import ManualChannel
from ocint.daemon.config import (
    DaemonConfig,
    DaemonSettings,
    LoadedDaemonConfig,
    OpenCodeConfig,
    RepositoryConfig,
    SchedulerConfig,
)
from ocint.daemon.db import create_daemon_engine, migrate_daemon_db
from ocint.daemon.git import GitHubPublisher, ManagedCommand, RepositoryManager
from ocint.daemon.models import JobState, WorkRequest, WorkSource
from ocint.daemon.outbox_repository import OutboxRepository
from ocint.daemon.repository import ControlRepository
from ocint.daemon.run import ActiveConfig, DaemonRunner
from ocint.daemon.runner_repository import RunnerRepository
from ocint.daemon.runtime import OpenCodeRuntime
from ocint.daemon.workspace_repository import WorkspaceRepository
from pydantic import HttpUrl


@pytest.mark.asyncio
async def test_two_live_runners_never_exceed_configured_execution_capacity(tmp_path: Path) -> None:
    # GIVEN three executable jobs, capacity two, two daemon runners, and an instrumented real HTTP runtime
    sessions: list[Mapping[str, str]] = []
    directories: list[Path] = []
    active_prompts: list[int] = []
    observed_max: list[int] = []
    release = asyncio.Event()

    async def health(_request: web.Request) -> web.Response:
        return web.json_response({"healthy": True, "version": "1.17.20"})

    async def list_sessions(request: web.Request) -> web.Response:
        directory = request.headers["x-opencode-directory"]
        return web.json_response([item for item in sessions if item["directory"] == directory])

    async def create_session(request: web.Request) -> web.Response:
        payload = await request.json()
        identifier = f"ses_{len(sessions) + 1}"
        directory = request.headers["x-opencode-directory"]
        session = {"id": identifier, "title": payload["title"], "directory": directory}
        sessions.append(session)
        directories.append(Path(directory))
        return web.json_response(session, status=201)

    async def messages(_request: web.Request) -> web.Response:
        return web.json_response([])

    async def prompt(request: web.Request) -> web.Response:
        directory = Path(request.headers["x-opencode-directory"])
        (directory / "capacity-e2e.txt").write_text("capacity change\n")
        active_prompts.append(1)
        observed_max.append(len(active_prompts))
        if len(active_prompts) == 2:
            release.set()
        await release.wait()
        active_prompts.pop()
        return web.Response(status=204)

    async def events(request: web.Request) -> web.StreamResponse:
        response = web.StreamResponse(headers={"Content-Type": "text/event-stream"})
        await response.prepare(request)
        await response.write(b'data: {"payload":{"type":"server.connected","properties":{}}}\n\n')
        await release.wait()
        await asyncio.sleep(0.05)
        for session in sessions:
            envelope = {
                "directory": session["directory"],
                "payload": {
                    "type": "session.status",
                    "properties": {"sessionID": session["id"], "status": {"type": "idle"}},
                },
            }
            await response.write(f"data: {json.dumps(envelope)}\n\n".encode())
        await response.write_eof()
        return response

    async def status_response(_request: web.Request) -> web.Response:
        return web.json_response({str(item["id"]): {"type": "idle"} for item in sessions})

    provider = web.Application()
    provider.add_routes(
        [
            web.get("/global/health", health),
            web.get("/global/event", events),
            web.get("/session", list_sessions),
            web.post("/session", create_session),
            web.get("/session/{session_id}/message", messages),
            web.post("/session/{session_id}/prompt_async", prompt),
            web.get("/session/status", status_response),
        ]
    )
    provider_runner = web.AppRunner(provider)
    await provider_runner.setup()
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    await web.SockSite(provider_runner, listener).start()
    provider_url = f"http://127.0.0.1:{listener.getsockname()[1]}"
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
    path = tmp_path / "control.sqlite"
    migrate_daemon_db(path)
    engine = create_daemon_engine(path)
    repository = ControlRepository(engine)
    config = DaemonConfig(
        database_path=path,
        mirror_root=tmp_path / "mirrors",
        worktree_root=tmp_path / "worktrees",
        repositories=[
            RepositoryConfig(
                name="repo",
                remote_url=str(remote),
                checks=[["python3", "-c", "from pathlib import Path; assert Path('capacity-e2e.txt').is_file()"]],
            )
        ],
        scheduler=SchedulerConfig(capacity=2, lease_seconds=10, heartbeat_seconds=1, poll_seconds=0.05),
        opencode=OpenCodeConfig(server_url=HttpUrl(provider_url), request_timeout_seconds=5),
    )
    settings = DaemonSettings(config=tmp_path / "daemon.toml")
    active = ActiveConfig(LoadedDaemonConfig(path=tmp_path / "daemon.toml", config=config, settings=settings), tmp_path)
    for number in range(3):
        repository.submit(
            WorkRequest(
                idempotency_key=f"capacity-{number}",
                conversation_id=f"manual-{number}",
                actor="actor",
                repository="repo",
                text=f"capacity job {number}",
                source=WorkSource.MANUAL,
                delivery_adapter="manual",
                delivery_target="manual",
            )
        )
    environment = {
        "PATH": "/usr/local/bin:/usr/bin:/bin",
        "LANG": "C.UTF-8",
        "HOME": str(tmp_path),
        "GIT_AUTHOR_NAME": "Daemon Test",
        "GIT_AUTHOR_EMAIL": "daemon@example.test",
        "GIT_COMMITTER_NAME": "Daemon Test",
        "GIT_COMMITTER_EMAIL": "daemon@example.test",
    }
    manager = RepositoryManager(
        config.mirror_root,
        config.worktree_root,
        ManagedCommand(10, 8192, frozenset()),
        {"PATH": environment["PATH"], "LANG": environment["LANG"], "CI": "1"},
        environment,
    )
    runtime = OpenCodeRuntime(provider_url, "", "", 5)
    await runtime.start()
    await runtime.health()
    submitted: list[WorkRequest] = []
    channel = ManualChannel(submitted.append)
    runner_one = DaemonRunner(
        active,
        repository,
        manager,
        runtime,
        GitHubPublisher(provider_url, ""),
        [channel],
        OutboxRepository(engine),
        RunnerRepository(engine, repository),
        WorkspaceRepository(engine),
    )
    runner_two = DaemonRunner(
        active,
        repository,
        manager,
        runtime,
        GitHubPublisher(provider_url, ""),
        [channel],
        OutboxRepository(engine),
        RunnerRepository(engine, repository),
        WorkspaceRepository(engine),
    )

    # WHEN both runners execute all competing jobs
    first_task = asyncio.create_task(runner_one.run())
    second_task = asyncio.create_task(runner_two.run())
    deadline = asyncio.get_running_loop().time() + 20
    while asyncio.get_running_loop().time() < deadline:
        if all(item.state is JobState.COMPLETED for item in repository.list()):
            break
        await asyncio.sleep(0.1)

    # THEN observed runtime concurrency never exceeds the configured durable capacity
    assert all(item.state is JobState.COMPLETED for item in repository.list())
    assert max(observed_max) == 2
    assert max(observed_max) <= config.scheduler.capacity
    runner_one.stopping.set()
    runner_two.stopping.set()
    await asyncio.gather(first_task, second_task)
    await runtime.close()
    await provider_runner.cleanup()
    engine.dispose()
