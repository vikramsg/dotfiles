import asyncio
import json
import socket
import subprocess
from collections.abc import Mapping
from pathlib import Path

import httpx
import pytest
from aiohttp import web
from ocint.daemon import run_daemon
from ocint.daemon.api import JobResponse
from ocint.daemon.config import DaemonSettings
from pydantic import TypeAdapter


@pytest.mark.asyncio
async def test_production_composition_processes_configured_github_job_end_to_end(tmp_path: Path) -> None:
    # GIVEN normal TOML/credential wiring, a bare Git remote, and stateful localhost providers
    prompts: list[str] = []
    sessions: list[Mapping[str, str]] = []
    pull_requests: list[Mapping[str, str | int]] = []
    comments: list[Mapping[str, str | int]] = []
    prompt_received = asyncio.Event()

    async def health(_request: web.Request) -> web.Response:
        return web.json_response({"healthy": True, "version": "1.17.20"})

    async def issues(_request: web.Request) -> web.Response:
        return web.json_response(
            [{"number": 17, "title": "Deterministic job", "body": "write the marker", "user": {"login": "bot"}}]
        )

    async def list_sessions(_request: web.Request) -> web.Response:
        return web.json_response(sessions)

    async def create_session(request: web.Request) -> web.Response:
        payload = await request.json()
        session = {"id": "ses_production", "title": payload["title"]}
        sessions.append(session)
        return web.json_response(session, status=201)

    async def messages(_request: web.Request) -> web.Response:
        return web.json_response([])

    async def prompt(request: web.Request) -> web.Response:
        payload = await request.json()
        prompts.append(payload["parts"][0]["text"])
        directory = Path(request.headers["x-opencode-directory"])
        (directory / "production-e2e.txt").write_text("production composition\n")
        prompt_received.set()
        return web.Response(status=204)

    async def events(request: web.Request) -> web.StreamResponse:
        response = web.StreamResponse(headers={"Content-Type": "text/event-stream"})
        await response.prepare(request)
        await response.write(b'data: {"payload":{"type":"server.connected","properties":{}}}\n\n')
        await prompt_received.wait()
        worktree = next((tmp_path / "worktrees").glob("*"))
        envelope = {
            "directory": str(worktree),
            "payload": {
                "type": "session.status",
                "properties": {"sessionID": "ses_production", "status": {"type": "idle"}},
            },
        }
        await response.write(f"data: {json.dumps(envelope)}\n\n".encode())
        await response.write_eof()
        return response

    async def status_response(_request: web.Request) -> web.Response:
        return web.json_response({"ses_production": {"type": "idle"}})

    async def list_pulls(_request: web.Request) -> web.Response:
        return web.json_response(pull_requests)

    async def create_pull(request: web.Request) -> web.Response:
        payload = await request.json()
        pull = {"html_url": "http://provider.local/pulls/1", "number": 1, "head": payload["head"]}
        pull_requests.append(pull)
        return web.json_response(pull, status=201)

    async def list_comments(_request: web.Request) -> web.Response:
        return web.json_response(comments)

    async def create_comment(request: web.Request) -> web.Response:
        payload = await request.json()
        comment = {"id": len(comments) + 1, "body": payload["body"]}
        comments.append(comment)
        return web.json_response(comment, status=201)

    async def update_comment(request: web.Request) -> web.Response:
        payload = await request.json()
        identifier = int(request.match_info["comment_id"])
        comments[identifier - 1] = {"id": identifier, "body": payload["body"]}
        return web.json_response(comments[identifier - 1])

    provider = web.Application()
    provider.add_routes(
        [
            web.get("/global/health", health),
            web.get("/global/event", events),
            web.get("/repos/owner/repo/issues", issues),
            web.get("/session", list_sessions),
            web.post("/session", create_session),
            web.get("/session/{session_id}/message", messages),
            web.post("/session/{session_id}/prompt_async", prompt),
            web.get("/session/status", status_response),
            web.get("/repos/owner/repo/pulls", list_pulls),
            web.post("/repos/owner/repo/pulls", create_pull),
            web.get("/repos/owner/repo/issues/17/comments", list_comments),
            web.post("/repos/owner/repo/issues/17/comments", create_comment),
            web.patch("/repos/owner/repo/issues/comments/{comment_id}", update_comment),
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

    control_socket = socket.socket()
    control_socket.bind(("127.0.0.1", 0))
    control_port = control_socket.getsockname()[1]
    control_socket.close()
    config_path = tmp_path / "daemon.toml"
    config_path.write_text(
        f'database_path = "{tmp_path / "control.sqlite"}"\n'
        f'mirror_root = "{tmp_path / "mirrors"}"\n'
        f'worktree_root = "{tmp_path / "worktrees"}"\n'
        "retention_seconds = 3600\n"
        '[[repositories]]\nname = "repo"\n'
        f'remote_url = "{remote}"\n'
        'default_branch = "main"\ngithub_repository = "owner/repo"\nactors = ["bot"]\n'
        'checks = [["python3", "-c", "from pathlib import Path; assert Path(\'production-e2e.txt\').is_file()"]]\n'
        "[scheduler]\ncapacity = 1\nlease_seconds = 10\nheartbeat_seconds = 1\npoll_seconds = 0.05\n"
        "job_timeout_seconds = 10\ncommand_timeout_seconds = 10\n"
        f'[opencode]\nserver_url = "{provider_url}"\nrequest_timeout_seconds = 5\nexpected_version = "1.17.20"\n'
        f'[api]\nhost = "127.0.0.1"\nport = {control_port}\n'
        f'[providers]\ngithub_api_url = "{provider_url}"\nslack_api_url = "{provider_url}"\n'
        f'slack_socket_url = "{provider_url}"\n'
        '[[channels.github]]\nrepository = "repo"\ngithub_repository = "owner/repo"\n'
        'label = "ocint"\npoll_seconds = 0.05\n'
    )
    credentials = tmp_path / "credentials"
    credentials.mkdir()
    (credentials / "daemon-api-token").write_text("api-token\n")
    (credentials / "github-token").write_text("github-token\n")
    (credentials / "opencode-password").write_text("server-password\n")
    (credentials / "git-config").write_text("[user]\n\tname = Daemon Test\n\temail = daemon@example.test\n")
    settings = DaemonSettings(
        config=config_path,
        credential_directory=credentials,
        publication_home=tmp_path,
    )

    # WHEN the production composition starts with configured GitHub polling
    daemon = asyncio.create_task(run_daemon(settings, tmp_path, []))
    deadline = asyncio.get_running_loop().time() + 20
    jobs: list[JobResponse] = []
    async with httpx.AsyncClient(headers={"Authorization": "Bearer api-token"}) as client:
        while asyncio.get_running_loop().time() < deadline:
            try:
                response = await client.get(f"http://127.0.0.1:{control_port}/api/jobs")
                jobs = TypeAdapter(list[JobResponse]).validate_python(response.json())
                if jobs and jobs[0].state == "completed":
                    break
            except httpx.ConnectError:
                pass
            await asyncio.sleep(0.1)

    # THEN the normal stack executes, validates, commits, pushes, publishes, notifies, and can shut down
    assert jobs
    assert jobs[0].state == "completed"
    assert prompts == ["Deterministic job\n\nwrite the marker"]
    assert len(pull_requests) == 1
    delivery_deadline = asyncio.get_running_loop().time() + 5
    while len(comments) < 2 and asyncio.get_running_loop().time() < delivery_deadline:
        await asyncio.sleep(0.1)
    assert len(comments) == 2
    branch = jobs[0].id
    subprocess.run(
        ["git", "--git-dir", str(remote), "rev-parse", f"refs/heads/ocint/{branch}"],
        check=True,
        capture_output=True,
    )
    daemon.cancel()
    with pytest.raises(asyncio.CancelledError):
        await daemon
    await provider_runner.cleanup()
