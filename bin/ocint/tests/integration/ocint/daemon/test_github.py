from dataclasses import dataclass

import pytest
from aiohttp import web
from ocint.daemon.github import GitHubClient


@dataclass
class ProviderState:
    created: int = 0


@pytest.mark.asyncio
async def test_pull_request_creation_is_idempotent(unused_tcp_port: int) -> None:
    # GIVEN
    state = ProviderState()

    async def pulls(request: web.Request) -> web.Response:
        if request.method == "GET":
            return web.json_response([] if state.created == 0 else [{"html_url": "https://example.test/pull/1"}])
        state.created += 1
        return web.json_response({"html_url": "https://example.test/pull/1"})

    app = web.Application()
    app.router.add_get("/repos/owner/repo/pulls", pulls)
    app.router.add_post("/repos/owner/repo/pulls", pulls)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "127.0.0.1", unused_tcp_port).start()
    client = GitHubClient(f"http://127.0.0.1:{unused_tcp_port}", "token")

    # WHEN
    first = await client.publish("owner/repo", "ocint/job", "main", "title", "body")
    second = await client.publish("owner/repo", "ocint/job", "main", "title", "body")

    # THEN
    assert first == second == "https://example.test/pull/1"
    assert state.created == 1
    await runner.cleanup()
