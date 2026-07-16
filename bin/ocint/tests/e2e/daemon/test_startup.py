import asyncio
import json
import socket
from pathlib import Path

import aiohttp
import pytest
from aiohttp import web
from ocint.daemon import run_daemon
from ocint.daemon.config import DaemonSettings


@pytest.mark.asyncio
async def test_production_composition_loads_config_verifies_opencode_and_serves_authenticated_api(
    tmp_path: Path,
) -> None:
    # GIVEN production run_daemon composition, file configuration, credentials, and a real HTTP OpenCode fake
    async def health(_request: web.Request) -> web.Response:
        return web.json_response({"healthy": True, "version": "1.17.20"})

    async def events(request: web.Request) -> web.StreamResponse:
        response = web.StreamResponse(headers={"Content-Type": "text/event-stream"})
        await response.prepare(request)
        envelope = {"payload": {"type": "server.connected", "properties": {}}}
        await response.write(f"data: {json.dumps(envelope)}\n\n".encode())
        await asyncio.sleep(30)
        return response

    provider = web.Application()
    provider.add_routes([web.get("/global/health", health), web.get("/global/event", events)])
    provider_runner = web.AppRunner(provider)
    await provider_runner.setup()
    provider_listener = socket.socket()
    provider_listener.bind(("127.0.0.1", 0))
    provider_listener.listen()
    await web.SockSite(provider_runner, provider_listener).start()
    provider_url = f"http://127.0.0.1:{provider_listener.getsockname()[1]}"

    control_listener = socket.socket()
    control_listener.bind(("127.0.0.1", 0))
    control_port = control_listener.getsockname()[1]
    control_listener.close()
    config_path = tmp_path / "daemon.toml"
    config_path.write_text(
        f'database_path = "{tmp_path / "control.sqlite"}"\n'
        f'mirror_root = "{tmp_path / "mirrors"}"\n'
        f'worktree_root = "{tmp_path / "worktrees"}"\n'
        'repositories = [{ name = "repo", remote_url = "file:///unused" }]\n'
        "[scheduler]\ncapacity = 1\nlease_seconds = 10\nheartbeat_seconds = 1\npoll_seconds = 0.05\n"
        f'[opencode]\nserver_url = "{provider_url}"\nexpected_version = "1.17.20"\n'
        f'[api]\nhost = "127.0.0.1"\nport = {control_port}\n'
        f'[providers]\ngithub_api_url = "{provider_url}"\nslack_api_url = "{provider_url}"\n'
        f'slack_socket_url = "{provider_url}"\n'
    )
    credentials = tmp_path / "credentials"
    credentials.mkdir()
    (credentials / "daemon-api-token").write_text("composition-token\n")
    (credentials / "opencode-password").write_text("server-password\n")
    (credentials / "git-config").write_text("[credential]\n\thelper = cache\n")
    settings = DaemonSettings(config=config_path, credential_directory=credentials, publication_home=tmp_path)

    # WHEN the real composition root starts
    daemon = asyncio.create_task(run_daemon(settings, tmp_path, []))
    deadline = asyncio.get_running_loop().time() + 10
    authenticated = False
    async with aiohttp.ClientSession() as client:
        while asyncio.get_running_loop().time() < deadline:
            try:
                async with client.get(
                    f"http://127.0.0.1:{control_port}/health",
                    headers={"Authorization": "Bearer composition-token"},
                ) as response:
                    authenticated = response.status == 200
                    if authenticated:
                        break
            except aiohttp.ClientConnectionError:
                pass
            await asyncio.sleep(0.05)
        async with client.get(f"http://127.0.0.1:{control_port}/health") as response:
            unauthenticated_status = response.status

    # THEN startup health gating and API authentication use production wiring
    assert authenticated
    assert unauthenticated_status == 401
    daemon.cancel()
    with pytest.raises(asyncio.CancelledError):
        await daemon
    await provider_runner.cleanup()
