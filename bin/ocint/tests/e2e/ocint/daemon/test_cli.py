import asyncio
import os
import subprocess
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

import aiohttp
import pytest
import uvicorn
from aiohttp import web
from ocint.daemon.cli import create_daemon_app
from ocint.daemon.config import DaemonSettings
from pydantic import SecretStr


@dataclass
class ProductionState:
    pull_requests_created: int = 0
    edited_worktree: Path | None = None


class SignalFreeServer(uvicorn.Server):
    @contextmanager
    def capture_signals(self) -> Iterator[None]:
        yield


@pytest.mark.asyncio
async def test_production_composition_completes_job_through_api(
    tmp_path: Path, unused_tcp_port_factory: Callable[[], int]
) -> None:
    # GIVEN
    api_port = unused_tcp_port_factory()
    opencode_port = unused_tcp_port_factory()
    github_port = unused_tcp_port_factory()
    state = ProductionState()

    async def opencode_health(_request: web.Request) -> web.Response:
        return web.json_response({"healthy": True, "version": "1.17.20"})

    async def opencode_sessions(request: web.Request) -> web.Response:
        if request.method == "GET":
            return web.json_response([])
        return web.json_response({"id": "session", "title": (await request.json())["title"]})

    async def opencode_messages(_request: web.Request) -> web.Response:
        return web.json_response([])

    async def opencode_prompt(request: web.Request) -> web.Response:
        worktree = Path(request.headers["x-opencode-directory"])
        (worktree / "result.txt").write_text("completed\n")
        state.edited_worktree = worktree
        return web.json_response({})

    async def opencode_status(_request: web.Request) -> web.Response:
        return web.json_response({})

    async def github_pulls(request: web.Request) -> web.Response:
        if request.method == "GET":
            return web.json_response([])
        state.pull_requests_created += 1
        return web.json_response({"html_url": "https://example.test/pull/1"})

    opencode_app = web.Application()
    opencode_app.router.add_get("/global/health", opencode_health)
    opencode_app.router.add_get("/session", opencode_sessions)
    opencode_app.router.add_post("/session", opencode_sessions)
    opencode_app.router.add_get("/session/{identifier}/message", opencode_messages)
    opencode_app.router.add_post("/session/{identifier}/prompt_async", opencode_prompt)
    opencode_app.router.add_get("/session/status", opencode_status)
    opencode_runner = web.AppRunner(opencode_app)
    await opencode_runner.setup()
    await web.TCPSite(opencode_runner, "127.0.0.1", opencode_port).start()

    github_app = web.Application()
    github_app.router.add_get("/repos/owner/repo/pulls", github_pulls)
    github_app.router.add_post("/repos/owner/repo/pulls", github_pulls)
    github_runner = web.AppRunner(github_app)
    await github_runner.setup()
    await web.TCPSite(github_runner, "127.0.0.1", github_port).start()

    remote = tmp_path / "remote.git"
    seed = tmp_path / "seed"
    subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True)
    subprocess.run(["git", "init", "-b", "main", str(seed)], check=True, capture_output=True)
    (seed / "README.md").write_text("seed\n")
    subprocess.run(["git", "-C", str(seed), "add", "README.md"], check=True)
    subprocess.run(
        ["git", "-C", str(seed), "-c", "user.name=Seed", "-c", "user.email=seed@example.test", "commit", "-m", "seed"],
        check=True,
        capture_output=True,
    )
    subprocess.run(["git", "-C", str(seed), "remote", "add", "origin", str(remote)], check=True)
    subprocess.run(["git", "-C", str(seed), "push", "origin", "main"], check=True, capture_output=True)

    transport = tmp_path / "bin"
    transport.mkdir()
    ssh = transport / "ssh"
    ssh.write_text('#!/bin/sh\nfor argument do command="$argument"; done\nexec sh -c "$command"\n')
    ssh.chmod(0o755)
    config = tmp_path / "daemon.toml"
    config.write_text(
        f'''database_path = "{tmp_path / "control.sqlite"}"
mirror_root = "{tmp_path / "mirrors"}"
worktree_root = "{tmp_path / "worktrees"}"
[[repositories]]
name = "repo"
remote_url = "ssh://example{remote}"
github_repository = "owner/repo"
author_name = "Daemon Agent"
author_email = "daemon@example.test"
actors = ["allowed"]
[scheduler]
capacity = 1
job_timeout_seconds = 10
shutdown_timeout_seconds = 5
[opencode]
server_url = "http://127.0.0.1:{opencode_port}"
username = "opencode"
request_timeout_seconds = 2
expected_version = "1.17.20"
[api]
host = "127.0.0.1"
port = {api_port}
[github]
api_url = "http://127.0.0.1:{github_port}"
'''
    )
    settings = DaemonSettings(
        config=config,
        api_token=SecretStr("api-token"),
        opencode_password=SecretStr("opencode-password"),
        github_token=SecretStr("github-token"),
        execution_path=f"{transport}:{os.environ['PATH']}",
        execution_lang="C.UTF-8",
        ssh_auth_sock="/tmp/test-agent",
    )
    app, _loaded = create_daemon_app(settings, tmp_path)
    server = SignalFreeServer(
        uvicorn.Config(app, host="127.0.0.1", port=api_port, log_config=None, access_log=False, lifespan="on")
    )
    daemon = asyncio.create_task(server.serve())

    # WHEN
    headers = {"Authorization": "Bearer api-token"}
    async with aiohttp.ClientSession(headers=headers) as client:
        for _attempt in range(100):
            try:
                async with client.get(f"http://127.0.0.1:{api_port}/health") as response:
                    if response.status == 200:
                        break
            except aiohttp.ClientConnectorError:
                pass
            await asyncio.sleep(0.02)
        async with client.post(
            f"http://127.0.0.1:{api_port}/api/jobs",
            json={"idempotency_key": "production", "actor": "allowed", "repository": "repo", "prompt": "edit"},
        ) as response:
            submitted = await response.json()
            assert response.status == 202
        for _attempt in range(500):
            async with client.get(f"http://127.0.0.1:{api_port}/api/jobs/{submitted['id']}") as response:
                completed = await response.json()
            if completed["state"] in {"completed", "failed"}:
                break
            await asyncio.sleep(0.02)
    server.should_exit = True
    await daemon

    # THEN
    assert completed["state"] == "completed"
    assert completed["commit_sha"]
    assert completed["pull_request_url"] == "https://example.test/pull/1"
    assert state.pull_requests_created == 1
    assert state.edited_worktree is not None
    remote_commit = subprocess.run(
        ["git", "--git-dir", str(remote), "rev-parse", f"refs/heads/ocint/{submitted['id']}"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert remote_commit == completed["commit_sha"]
    await github_runner.cleanup()
    await opencode_runner.cleanup()
