import asyncio
import time
from collections.abc import AsyncIterator
from pathlib import Path

import aiohttp
import pytest
import pytest_asyncio
from aiohttp import web
from ocint.daemon.opencode import OpenCodeClient
from pydantic import BaseModel, ConfigDict


class WirePart(BaseModel):
    model_config = ConfigDict(frozen=True)
    type: str
    text: str


class WireInfo(BaseModel):
    model_config = ConfigDict(frozen=True)
    role: str
    finish: str | None = None


class WireMessage(BaseModel):
    model_config = ConfigDict(frozen=True)
    info: WireInfo
    parts: list[WirePart]


class WireStatus(BaseModel):
    model_config = ConfigDict(frozen=True)
    type: str


class WireStatuses(BaseModel):
    model_config = ConfigDict(frozen=True)
    session: WireStatus


class OpenCodeHttpFake:
    def __init__(self) -> None:
        self.messages = [WireMessage(info=WireInfo(role="user"), parts=[WirePart(type="text", text="perform work")])]
        self.session_status: str | None = "idle"
        self.status_requests = 0
        self.app = web.Application()
        self.app.router.add_get("/session/session/message", self.message_list)
        self.app.router.add_get("/session/status", self.status)
        self.app.router.add_get("/global/event", self.events)
        self.runner = web.AppRunner(self.app)
        self.port = 0

    async def start(self, port: int) -> None:
        self.port = port
        await self.runner.setup()
        await web.TCPSite(self.runner, "127.0.0.1", port).start()

    async def close(self) -> None:
        await self.runner.cleanup()

    def complete(self) -> None:
        self.messages.append(
            WireMessage(
                info=WireInfo(role="assistant", finish="stop"),
                parts=[WirePart(type="text", text="completed")],
            )
        )

    def interrupt(self) -> None:
        self.messages.append(
            WireMessage(
                info=WireInfo(role="assistant"),
                parts=[WirePart(type="tool", text="pending apply_patch")],
            )
        )

    async def message_list(self, _request: web.Request) -> web.Response:
        return web.json_response([message.model_dump(mode="json") for message in self.messages])

    async def status(self, _request: web.Request) -> web.Response:
        self.status_requests += 1
        if self.session_status is None:
            return web.json_response({})
        payload = WireStatuses(session=WireStatus(type=self.session_status))
        return web.json_response(payload.model_dump(mode="json"))

    async def events(self, _request: web.Request) -> web.Response:
        return web.Response(text="")


@pytest_asyncio.fixture
async def opencode_server(unused_tcp_port: int) -> AsyncIterator[OpenCodeHttpFake]:
    server = OpenCodeHttpFake()
    await server.start(unused_tcp_port)
    yield server
    await server.close()


@pytest.mark.asyncio
async def test_immediate_idle_requires_completed_assistant_evidence(
    tmp_path: Path, opencode_server: OpenCodeHttpFake
) -> None:
    # GIVEN
    client = OpenCodeClient(
        f"http://127.0.0.1:{opencode_server.port}",
        "opencode",
        "ephemeral",
        1,
        3,
        "1.17.20",
        tmp_path / "opencode",
        tmp_path / "config.json",
        tmp_path / "isolated-config",
        tmp_path / "existing-data",
        1,
        1,
        "/usr/bin:/bin",
        "C.UTF-8",
    )
    client.client = aiohttp.ClientSession(headers=client.headers, timeout=client.request_timeout)

    # WHEN
    waiting = asyncio.create_task(client.wait_for_completion(tmp_path, "session", "perform work"))
    await asyncio.sleep(0.2)

    # THEN
    assert not waiting.done()
    opencode_server.complete()
    await asyncio.wait_for(waiting, 1)
    await client.close()


@pytest.mark.asyncio
async def test_response_returns_terminal_assistant_text(tmp_path: Path, opencode_server: OpenCodeHttpFake) -> None:
    # GIVEN
    opencode_server.complete()
    client = OpenCodeClient(
        f"http://127.0.0.1:{opencode_server.port}",
        "opencode",
        "ephemeral",
        1,
        3,
        "1.17.20",
        tmp_path / "opencode",
        tmp_path / "config.json",
        tmp_path / "isolated-config",
        tmp_path / "existing-data",
        1,
        1,
        "/usr/bin:/bin",
        "C.UTF-8",
    )
    client.client = aiohttp.ClientSession(headers=client.headers, timeout=client.request_timeout)

    # WHEN
    response = await client.response(tmp_path, "session", "perform work")

    # THEN
    assert response == "completed"
    await client.close()


@pytest.mark.asyncio
async def test_incomplete_active_prompt_is_observed_as_processing(
    tmp_path: Path, opencode_server: OpenCodeHttpFake
) -> None:
    # GIVEN
    opencode_server.interrupt()
    opencode_server.session_status = "busy"
    client = OpenCodeClient(
        f"http://127.0.0.1:{opencode_server.port}",
        "opencode",
        "ephemeral",
        1,
        3,
        "1.17.20",
        tmp_path / "opencode",
        tmp_path / "config.json",
        tmp_path / "isolated-config",
        tmp_path / "existing-data",
        1,
        1,
        "/usr/bin:/bin",
        "C.UTF-8",
    )
    client.client = aiohttp.ClientSession(headers=client.headers, timeout=client.request_timeout)

    # WHEN
    observation = await client.observe_prompt(tmp_path, "session", "perform work")

    # THEN
    assert observation.found
    assert not observation.completed
    assert observation.active
    assert opencode_server.status_requests == 1
    await client.close()


@pytest.mark.parametrize("status", ["idle", None])
@pytest.mark.asyncio
async def test_incomplete_inactive_prompt_is_observed_as_interrupted(
    tmp_path: Path, opencode_server: OpenCodeHttpFake, status: str | None
) -> None:
    # GIVEN
    opencode_server.interrupt()
    opencode_server.session_status = status
    client = OpenCodeClient(
        f"http://127.0.0.1:{opencode_server.port}",
        "opencode",
        "ephemeral",
        1,
        3,
        "1.17.20",
        tmp_path / "opencode",
        tmp_path / "config.json",
        tmp_path / "isolated-config",
        tmp_path / "existing-data",
        1,
        1,
        "/usr/bin:/bin",
        "C.UTF-8",
    )
    client.client = aiohttp.ClientSession(headers=client.headers, timeout=client.request_timeout)

    # WHEN
    observation = await client.observe_prompt(tmp_path, "session", "perform work")

    # THEN
    assert observation.found
    assert not observation.completed
    assert not observation.active
    assert opencode_server.status_requests == 1
    await client.close()


@pytest.mark.asyncio
async def test_agent_execution_can_exceed_individual_request_timeout(
    tmp_path: Path, opencode_server: OpenCodeHttpFake
) -> None:
    # GIVEN
    client = OpenCodeClient(
        f"http://127.0.0.1:{opencode_server.port}",
        "opencode",
        "ephemeral",
        1,
        3,
        "1.17.20",
        tmp_path / "opencode",
        tmp_path / "config.json",
        tmp_path / "isolated-config",
        tmp_path / "existing-data",
        1,
        1,
        "/usr/bin:/bin",
        "C.UTF-8",
    )
    client.client = aiohttp.ClientSession(headers=client.headers, timeout=client.request_timeout)
    waiting = asyncio.create_task(client.wait_for_completion(tmp_path, "session", "perform work"))

    # WHEN
    await asyncio.sleep(1.2)
    opencode_server.complete()
    await asyncio.wait_for(waiting, 1)

    # THEN
    assert not client.client.closed
    await client.close()


@pytest.mark.asyncio
async def test_completion_requires_the_managed_prompt_to_be_the_latest_user_turn(
    tmp_path: Path, opencode_server: OpenCodeHttpFake
) -> None:
    # GIVEN
    opencode_server.complete()
    opencode_server.messages.append(
        WireMessage(info=WireInfo(role="user"), parts=[WirePart(type="text", text="different work")])
    )
    client = OpenCodeClient(
        f"http://127.0.0.1:{opencode_server.port}",
        "opencode",
        "ephemeral",
        1,
        3,
        "1.17.20",
        tmp_path / "opencode",
        tmp_path / "config.json",
        tmp_path / "isolated-config",
        tmp_path / "existing-data",
        1,
        1,
        "/usr/bin:/bin",
        "C.UTF-8",
    )
    client.client = aiohttp.ClientSession(headers=client.headers, timeout=client.request_timeout)

    # WHEN
    observation = await client.observe_prompt(tmp_path, "session", "perform work")

    # THEN
    assert not observation.found
    assert not observation.completed
    await client.close()


def test_child_process_uses_isolated_config_and_existing_auth_data_home(tmp_path: Path) -> None:
    # GIVEN
    client = OpenCodeClient(
        "http://127.0.0.1:4096",
        "opencode",
        "ephemeral",
        1,
        3,
        "1.17.20",
        tmp_path / "opencode",
        tmp_path / "isolated-config" / "opencode" / "opencode.json",
        tmp_path / "isolated-config",
        tmp_path / "existing-data",
        1,
        1,
        "/usr/bin:/bin",
        "C.UTF-8",
    )

    # WHEN
    environment = client.child_environment()
    arguments = client.serve_arguments("4096")

    # THEN
    assert environment["HOME"] == str(tmp_path / "isolated-config" / "home")
    assert environment["XDG_CONFIG_HOME"] == str(tmp_path / "isolated-config")
    assert environment["XDG_DATA_HOME"] == str(tmp_path / "existing-data")
    assert environment["OPENCODE_CONFIG"] == str(tmp_path / "isolated-config" / "opencode" / "opencode.json")
    assert "--pure" in arguments
    assert "plugin" not in environment
    assert "instructions" not in environment


@pytest.mark.asyncio
async def test_startup_retries_an_individual_health_request_timeout(tmp_path: Path, unused_tcp_port: int) -> None:
    # GIVEN
    executable = tmp_path / "delayed-health"
    executable.write_text(
        """#!/usr/bin/env python3
import sys
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

port = int(sys.argv[sys.argv.index("--port") + 1])

class Handler(BaseHTTPRequestHandler):
    requests = 0

    def do_GET(self):
        Handler.requests += 1
        if Handler.requests == 1:
            time.sleep(1.2)
        body = b'{"healthy": true, "version": "1.17.20"}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except BrokenPipeError:
            pass

    def log_message(self, format, *args):
        pass

HTTPServer(("127.0.0.1", port), Handler).serve_forever()
"""
    )
    executable.chmod(0o755)
    client = OpenCodeClient(
        f"http://127.0.0.1:{unused_tcp_port}",
        "opencode",
        "ephemeral",
        1,
        3,
        "1.17.20",
        executable,
        tmp_path / "isolated-config" / "opencode" / "opencode.json",
        tmp_path / "isolated-config",
        tmp_path / "isolated-data",
        5,
        1,
        "/usr/bin:/bin",
        "C.UTF-8",
    )

    # WHEN
    started_at = time.monotonic()
    await client.start()

    # THEN
    assert time.monotonic() - started_at >= 1
    await client.close()
