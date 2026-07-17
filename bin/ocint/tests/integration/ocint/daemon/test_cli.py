from pathlib import Path

import pytest
from aiohttp import web
from ocint.daemon.cli import create_daemon_app
from ocint.daemon.config import DaemonSettings
from pydantic import SecretStr


def test_app_factory_validates_credentials_before_creating_database(tmp_path: Path) -> None:
    # GIVEN
    database = tmp_path / "control.sqlite"
    config = tmp_path / "daemon.toml"
    config.write_text(
        f'''database_path = "{database}"
mirror_root = "{tmp_path / "mirrors"}"
worktree_root = "{tmp_path / "worktrees"}"
[[repositories]]
name = "repo"
remote_url = "git@example.test:owner/repo.git"
github_repository = "owner/repo"
author_name = "Agent"
author_email = "agent@example.test"
'''
    )

    # WHEN / THEN
    with pytest.raises(ValueError, match="API_TOKEN"):
        create_daemon_app(DaemonSettings(config=config), tmp_path)
    assert not database.exists()


@pytest.mark.asyncio
async def test_fastapi_lifespan_closes_after_opencode_health_failure(tmp_path: Path, unused_tcp_port: int) -> None:
    # GIVEN
    async def unhealthy(_request: web.Request) -> web.Response:
        return web.json_response({"healthy": True, "version": "wrong"})

    opencode_app = web.Application()
    opencode_app.router.add_get("/global/health", unhealthy)
    runner = web.AppRunner(opencode_app)
    await runner.setup()
    await web.TCPSite(runner, "127.0.0.1", unused_tcp_port).start()
    database = tmp_path / "control.sqlite"
    config = tmp_path / "daemon.toml"
    config.write_text(
        f'''database_path = "{database}"
mirror_root = "{tmp_path / "mirrors"}"
worktree_root = "{tmp_path / "worktrees"}"
[[repositories]]
name = "repo"
remote_url = "git@example.test:owner/repo.git"
github_repository = "owner/repo"
author_name = "Agent"
author_email = "agent@example.test"
[opencode]
server_url = "http://127.0.0.1:{unused_tcp_port}"
expected_version = "1.17.20"
'''
    )
    settings = DaemonSettings(
        config=config,
        api_token=SecretStr("api"),
        opencode_password=SecretStr("opencode"),
        github_token=SecretStr("github"),
        ssh_auth_sock="/tmp/agent",
    )
    app, _loaded = create_daemon_app(settings, tmp_path)

    # WHEN / THEN
    with pytest.raises(RuntimeError, match="version mismatch"):
        async with app.router.lifespan_context(app):
            pass
    assert database.exists()
    await runner.cleanup()
