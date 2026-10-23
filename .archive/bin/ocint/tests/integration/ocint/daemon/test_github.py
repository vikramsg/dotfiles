from pathlib import Path

import pytest
from aiohttp import web
from ocint.daemon.db import migrate_daemon_db
from ocint.daemon.github import (
    GitHubConfig,
    GitHubGateway,
    GitHubRepositoryPolicies,
    GitHubRepositoryPolicy,
    open_github_service,
)
from ocint.daemon.models import GitHubLogin
from pydantic import HttpUrl


class ContextBodyFailure(RuntimeError):
    pass


@pytest.mark.asyncio
async def test_factory_closes_owned_client_when_context_body_fails(tmp_path: Path, unused_tcp_port: int) -> None:
    # GIVEN
    async def issues(_request: web.Request) -> web.Response:
        return web.json_response([])

    app = web.Application()
    app.router.add_get("/repos/owner/repo/issues", issues)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "127.0.0.1", unused_tcp_port).start()
    database = tmp_path / "control.sqlite"
    migrate_daemon_db(database)
    yielded: list[GitHubGateway] = []

    # WHEN
    failed = False
    try:
        async with open_github_service(
            GitHubConfig(
                api_url=HttpUrl(f"http://127.0.0.1:{unused_tcp_port}"),
                agent_actor=GitHubLogin("automation-bot"),
            ),
            GitHubRepositoryPolicies(
                root=[
                    GitHubRepositoryPolicy(
                        name="repo",
                        github_repository="owner/repo",
                        actors=frozenset((GitHubLogin("maintainer"),)),
                    )
                ]
            ),
            "token",
            database,
        ) as github:
            yielded.append(github)
            assert (await github.observe()).root == []
            raise ContextBodyFailure("context body failed")
    except ContextBodyFailure:
        failed = True
    finally:
        await runner.cleanup()

    # THEN
    assert failed
    assert len(yielded) == 1
    with pytest.raises(RuntimeError, match="GitHub client is not started"):
        await yielded[0].observe()
