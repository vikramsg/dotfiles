import asyncio
import time
from collections.abc import AsyncIterator
from pathlib import Path

import aiohttp
import pytest
import pytest_asyncio
from aiohttp import web
from ocint.daemon.opencode import (
    OpenCodeConfig,
    OpenCodePrompt,
    OpenCodeRuntimeConfig,
    RetryableOpenCodeError,
    TerminalOpenCodeError,
)
from ocint.daemon.opencode.service import OpenCodeClient
from pydantic import BaseModel, ConfigDict, Field, HttpUrl


class WirePart(BaseModel):
    model_config = ConfigDict(frozen=True)
    type: str
    text: str


class WireErrorData(BaseModel):
    model_config = ConfigDict(frozen=True, populate_by_name=True)
    message: str
    is_retryable: bool = Field(alias="isRetryable")


class WireError(BaseModel):
    model_config = ConfigDict(frozen=True)
    name: str
    data: WireErrorData


class WireInfo(BaseModel):
    model_config = ConfigDict(frozen=True, populate_by_name=True)
    id: str
    role: str
    parent_id: str = Field(default="", alias="parentID")
    finish: str | None = None
    error: WireError | None = None


class WireMessage(BaseModel):
    model_config = ConfigDict(frozen=True)
    info: WireInfo
    parts: list[WirePart]


class WirePrompt(BaseModel):
    model_config = ConfigDict(frozen=True, populate_by_name=True)
    message_id: str = Field(alias="messageID")
    parts: list[WirePart]


class WireStatus(BaseModel):
    model_config = ConfigDict(frozen=True)
    type: str


class WireStatuses(BaseModel):
    model_config = ConfigDict(frozen=True)
    session: WireStatus


class ContractRequest(BaseModel):
    model_config = ConfigDict(frozen=True)
    method: str
    path: str
    body: WirePrompt


class ContractResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    status: int
    messages: tuple[WireMessage, ...]


class OpenCodeContract(BaseModel):
    model_config = ConfigDict(frozen=True)
    version: str
    request: ContractRequest
    response: ContractResponse


class OpenCodeHttpFake:
    def __init__(self) -> None:
        self.messages = [
            WireMessage(
                info=WireInfo(id="msg-user-legacy", role="user"),
                parts=[WirePart(type="text", text="perform work")],
            )
        ]
        self.submitted_prompt: WirePrompt | None = None
        self.session_status: str | None = "idle"
        self.status_requests = 0
        self.message_status = 200
        self.app = web.Application()
        self.app.router.add_get("/session/session/message", self.message_list)
        self.app.router.add_post("/session/session/prompt_async", self.prompt_async)
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
                info=WireInfo(id="msg-assistant-legacy", role="assistant", parentID="msg-user-legacy", finish="stop"),
                parts=[WirePart(type="text", text="completed")],
            )
        )

    def complete_correlated(self, parent_id: str) -> None:
        self.messages.append(
            WireMessage(
                info=WireInfo(id="msg-assistant-coordinator", role="assistant", parentID=parent_id, finish="stop"),
                parts=[
                    WirePart(type="text", text="first"),
                    WirePart(type="reasoning", text="private chain"),
                    WirePart(type="text", text="\nsecond"),
                    WirePart(type="tool", text="private tool output"),
                ],
            )
        )

    def interrupt(self, parent_id: str = "msg-user-legacy") -> None:
        self.messages.append(
            WireMessage(
                info=WireInfo(id="msg-assistant-interrupted", role="assistant", parentID=parent_id),
                parts=[WirePart(type="tool", text="pending apply_patch")],
            )
        )

    def fail(self, retryable: bool = False, parent_id: str = "msg-user-legacy") -> None:
        self.messages.append(
            WireMessage(
                info=WireInfo(
                    id="msg-assistant-error",
                    role="assistant",
                    parentID=parent_id,
                    finish="error",
                    error=WireError(
                        name="ProviderRequestError",
                        data=WireErrorData(
                            message="selected service tier was rejected",
                            isRetryable=retryable,
                        ),
                    ),
                ),
                parts=[],
            )
        )

    async def message_list(self, _request: web.Request) -> web.Response:
        return web.json_response(
            [message.model_dump(mode="json", by_alias=True) for message in self.messages],
            status=self.message_status,
        )

    async def prompt_async(self, request: web.Request) -> web.Response:
        prompt = WirePrompt.model_validate(await request.json())
        self.submitted_prompt = prompt
        self.messages.append(
            WireMessage(
                info=WireInfo(id=prompt.message_id, role="user"),
                parts=prompt.parts,
            )
        )
        return web.json_response({}, status=202)

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


@pytest.fixture
def opencode_config(tmp_path: Path, opencode_server: OpenCodeHttpFake) -> OpenCodeRuntimeConfig:
    return OpenCodeRuntimeConfig(
        service=OpenCodeConfig(
            server_url=HttpUrl(f"http://127.0.0.1:{opencode_server.port}"),
            request_timeout_seconds=1,
            executable=tmp_path / "opencode",
            config_file=tmp_path / "config.json",
            xdg_config_home=tmp_path / "isolated-config",
            xdg_data_home=tmp_path / "existing-data",
            startup_timeout_seconds=1,
            shutdown_timeout_seconds=1,
        ),
        password="ephemeral",
        execution_timeout_seconds=3,
        process_path="/usr/bin:/bin",
        process_lang="C.UTF-8",
    )


@pytest.mark.asyncio
async def test_immediate_idle_requires_completed_assistant_evidence(
    tmp_path: Path, opencode_server: OpenCodeHttpFake, opencode_config: OpenCodeRuntimeConfig
) -> None:
    # GIVEN
    client = OpenCodeClient(opencode_config)
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
async def test_incomplete_active_prompt_is_observed_as_processing(
    tmp_path: Path, opencode_server: OpenCodeHttpFake, opencode_config: OpenCodeRuntimeConfig
) -> None:
    # GIVEN
    opencode_server.interrupt()
    opencode_server.session_status = "busy"
    client = OpenCodeClient(opencode_config)
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
    tmp_path: Path,
    opencode_server: OpenCodeHttpFake,
    opencode_config: OpenCodeRuntimeConfig,
    status: str | None,
) -> None:
    # GIVEN
    opencode_server.interrupt()
    opencode_server.session_status = status
    client = OpenCodeClient(opencode_config)
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
    tmp_path: Path, opencode_server: OpenCodeHttpFake, opencode_config: OpenCodeRuntimeConfig
) -> None:
    # GIVEN
    client = OpenCodeClient(opencode_config)
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
async def test_terminal_assistant_error_fails_without_waiting_for_execution_timeout(
    tmp_path: Path, opencode_server: OpenCodeHttpFake, opencode_config: OpenCodeRuntimeConfig
) -> None:
    # GIVEN
    opencode_server.fail()
    client = OpenCodeClient(opencode_config.model_copy(update={"execution_timeout_seconds": 30}))
    client.client = aiohttp.ClientSession(headers=client.headers, timeout=client.request_timeout)

    # WHEN / THEN
    with pytest.raises(
        TerminalOpenCodeError,
        match="OpenCode session session failed: ProviderRequestError: selected service tier was rejected",
    ):
        await asyncio.wait_for(client.wait_for_completion(tmp_path, "session", "perform work"), 1)
    await client.close()


@pytest.mark.asyncio
async def test_active_retryable_assistant_error_remains_in_progress(
    tmp_path: Path, opencode_server: OpenCodeHttpFake, opencode_config: OpenCodeRuntimeConfig
) -> None:
    # GIVEN
    opencode_server.fail(retryable=True)
    opencode_server.session_status = "busy"
    client = OpenCodeClient(opencode_config)
    client.client = aiohttp.ClientSession(headers=client.headers, timeout=client.request_timeout)

    # WHEN
    observation = await client.observe_prompt(tmp_path, "session", "perform work")

    # THEN
    assert observation.found
    assert observation.active
    assert not observation.completed
    await client.close()


@pytest.mark.asyncio
async def test_correlated_prompt_uses_caller_id_and_returns_ordered_text_parts(
    tmp_path: Path, opencode_server: OpenCodeHttpFake, opencode_config: OpenCodeRuntimeConfig
) -> None:
    # GIVEN
    prompt = OpenCodePrompt(message_id="msg-user-coordinator-turn-0001", text="coordinate this turn")
    client = OpenCodeClient(opencode_config)
    client.client = aiohttp.ClientSession(headers=client.headers, timeout=client.request_timeout)

    # WHEN
    await client.submit_prompt(tmp_path, "session", prompt)
    opencode_server.complete_correlated(prompt.message_id)
    response = await client.wait_for_response(tmp_path, "session", prompt)

    # THEN
    assert opencode_server.submitted_prompt == WirePrompt(
        messageID="msg-user-coordinator-turn-0001",
        parts=[WirePart(type="text", text="coordinate this turn")],
    )
    assert response.assistant_message_id == "msg-assistant-coordinator"
    assert response.parent_message_id == "msg-user-coordinator-turn-0001"
    assert response.text == "first\nsecond"
    await client.close()


def test_real_1_18_15_contract_fixture_preserves_request_response_correlation_shape() -> None:
    # GIVEN
    fixture = OpenCodeContract.model_validate_json(
        (Path(__file__).parents[4] / "fixtures/contracts/opencode-1.18.15-correlated-prompt.json").read_text()
    )
    user_message, assistant_message = fixture.response.messages

    # WHEN
    ordered_text = "".join(part.text for part in assistant_message.parts if part.type == "text")

    # THEN
    assert fixture.version == "1.18.15"
    assert fixture.request.method == "POST"
    assert fixture.request.path.endswith("/prompt_async")
    assert fixture.response.status == 202
    assert fixture.request.body.message_id == user_message.info.id
    assert fixture.request.body.parts == user_message.parts
    assert user_message.info.role == "user"
    assert assistant_message.info.role == "assistant"
    assert assistant_message.info.parent_id == user_message.info.id
    assert assistant_message.info.finish == "stop"
    assert ordered_text == "CONTRACT-PROBE-OK"


@pytest.mark.asyncio
async def test_correlated_observation_uses_message_id_instead_of_prompt_text(
    tmp_path: Path, opencode_server: OpenCodeHttpFake, opencode_config: OpenCodeRuntimeConfig
) -> None:
    # GIVEN
    prompt = OpenCodePrompt(message_id="msg-user-coordinator-turn-0002", text="original text")
    client = OpenCodeClient(opencode_config)
    client.client = aiohttp.ClientSession(headers=client.headers, timeout=client.request_timeout)
    await client.submit_prompt(tmp_path, "session", prompt)
    opencode_server.complete_correlated(prompt.message_id)

    # WHEN
    observation = await client.observe_response(
        tmp_path,
        "session",
        prompt.model_copy(update={"text": "text changed after submission"}),
    )

    # THEN
    assert observation.found
    assert observation.completed
    assert not observation.active
    await client.close()


@pytest.mark.asyncio
async def test_correlated_observation_ignores_assistant_for_another_parent(
    tmp_path: Path, opencode_server: OpenCodeHttpFake, opencode_config: OpenCodeRuntimeConfig
) -> None:
    # GIVEN
    prompt = OpenCodePrompt(message_id="msg-user-coordinator-turn-parent", text="parented turn")
    client = OpenCodeClient(opencode_config)
    client.client = aiohttp.ClientSession(headers=client.headers, timeout=client.request_timeout)
    await client.submit_prompt(tmp_path, "session", prompt)
    opencode_server.complete_correlated("msg-user-unrelated")

    # WHEN
    observation = await client.observe_response(tmp_path, "session", prompt)

    # THEN
    assert observation.found
    assert not observation.completed
    assert not observation.active
    await client.close()


@pytest.mark.asyncio
async def test_correlated_inactive_unfinished_assistant_is_interrupted(
    tmp_path: Path, opencode_server: OpenCodeHttpFake, opencode_config: OpenCodeRuntimeConfig
) -> None:
    # GIVEN
    prompt = OpenCodePrompt(message_id="msg-user-coordinator-turn-0003", text="interrupt this turn")
    client = OpenCodeClient(opencode_config)
    client.client = aiohttp.ClientSession(headers=client.headers, timeout=client.request_timeout)
    await client.submit_prompt(tmp_path, "session", prompt)
    opencode_server.interrupt(prompt.message_id)

    # WHEN
    observation = await client.observe_response(tmp_path, "session", prompt)

    # THEN
    assert observation.found
    assert not observation.completed
    assert not observation.active
    await client.close()


@pytest.mark.asyncio
async def test_correlated_terminal_assistant_error_fails_for_its_parent(
    tmp_path: Path, opencode_server: OpenCodeHttpFake, opencode_config: OpenCodeRuntimeConfig
) -> None:
    # GIVEN
    prompt = OpenCodePrompt(message_id="msg-user-coordinator-turn-0004", text="failing turn")
    client = OpenCodeClient(opencode_config.model_copy(update={"execution_timeout_seconds": 30}))
    client.client = aiohttp.ClientSession(headers=client.headers, timeout=client.request_timeout)
    await client.submit_prompt(tmp_path, "session", prompt)
    opencode_server.fail(parent_id=prompt.message_id)

    # WHEN / THEN
    with pytest.raises(
        TerminalOpenCodeError,
        match="OpenCode session session failed: ProviderRequestError: selected service tier was rejected",
    ):
        await asyncio.wait_for(client.observe_response(tmp_path, "session", prompt), 1)
    await client.close()


@pytest.mark.asyncio
async def test_correlated_retryable_provider_error_is_classified_for_durable_retry(
    tmp_path: Path, opencode_server: OpenCodeHttpFake, opencode_config: OpenCodeRuntimeConfig
) -> None:
    # GIVEN
    prompt = OpenCodePrompt(message_id="msg-user-retryable", text="retry this turn")
    client = OpenCodeClient(opencode_config)
    client.client = aiohttp.ClientSession(headers=client.headers, timeout=client.request_timeout)
    await client.submit_prompt(tmp_path, "session", prompt)
    opencode_server.fail(retryable=True, parent_id=prompt.message_id)

    # WHEN / THEN
    with pytest.raises(RetryableOpenCodeError, match="selected service tier was rejected"):
        await client.observe_response(tmp_path, "session", prompt)
    await client.close()


@pytest.mark.asyncio
async def test_http_5xx_before_response_is_classified_for_durable_retry(
    tmp_path: Path, opencode_server: OpenCodeHttpFake, opencode_config: OpenCodeRuntimeConfig
) -> None:
    # GIVEN
    opencode_server.message_status = 503
    client = OpenCodeClient(opencode_config)
    client.client = aiohttp.ClientSession(headers=client.headers, timeout=client.request_timeout)

    # WHEN / THEN
    with pytest.raises(RetryableOpenCodeError, match="OpenCode HTTP 503"):
        await client.observe_response(
            tmp_path,
            "session",
            OpenCodePrompt(message_id="msg-user-transient", text="transient turn"),
        )
    await client.close()


@pytest.mark.asyncio
async def test_completion_requires_the_managed_prompt_to_be_the_latest_user_turn(
    tmp_path: Path, opencode_server: OpenCodeHttpFake, opencode_config: OpenCodeRuntimeConfig
) -> None:
    # GIVEN
    opencode_server.complete()
    opencode_server.messages.append(
        WireMessage(
            info=WireInfo(id="msg-user-different", role="user"),
            parts=[WirePart(type="text", text="different work")],
        )
    )
    client = OpenCodeClient(opencode_config)
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
        OpenCodeRuntimeConfig(
            service=OpenCodeConfig(
                server_url=HttpUrl("http://127.0.0.1:4096"),
                request_timeout_seconds=1,
                executable=tmp_path / "opencode",
                config_file=tmp_path / "isolated-config" / "opencode" / "opencode.json",
                xdg_config_home=tmp_path / "isolated-config",
                xdg_data_home=tmp_path / "existing-data",
                startup_timeout_seconds=1,
                shutdown_timeout_seconds=1,
            ),
            password="ephemeral",
            execution_timeout_seconds=3,
            process_path="/usr/bin:/bin",
            process_lang="C.UTF-8",
        )
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
    assert "--print-logs" not in arguments
    assert "plugin" not in environment
    assert "instructions" not in environment


@pytest.mark.asyncio
async def test_child_process_output_is_not_inherited_by_the_coordinator(
    tmp_path: Path,
    unused_tcp_port: int,
    capfd: pytest.CaptureFixture[str],
) -> None:
    # GIVEN
    executable = tmp_path / "noisy-opencode"
    executable.write_text(
        """#!/usr/bin/env python3
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer

print("PROHIBITED_PROVIDER_STDOUT", flush=True)
print("PROHIBITED_PROVIDER_STDERR", file=sys.stderr, flush=True)
port = int(sys.argv[sys.argv.index("--port") + 1])

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        body = b'{"healthy": true, "version": "1.18.15"}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        pass

HTTPServer(("127.0.0.1", port), Handler).serve_forever()
"""
    )
    executable.chmod(0o755)
    client = OpenCodeClient(
        OpenCodeRuntimeConfig(
            service=OpenCodeConfig(
                server_url=HttpUrl(f"http://127.0.0.1:{unused_tcp_port}"),
                request_timeout_seconds=1,
                executable=executable,
                config_file=tmp_path / "isolated-config" / "opencode" / "opencode.json",
                xdg_config_home=tmp_path / "isolated-config",
                xdg_data_home=tmp_path / "isolated-data",
                startup_timeout_seconds=3,
                shutdown_timeout_seconds=1,
            ),
            password="ephemeral",
            execution_timeout_seconds=3,
            process_path="/usr/bin:/bin",
            process_lang="C.UTF-8",
        )
    )

    # WHEN
    await client.start()
    await client.close()
    captured = capfd.readouterr()

    # THEN
    assert "PROHIBITED_PROVIDER_STDOUT" not in captured.out
    assert "PROHIBITED_PROVIDER_STDERR" not in captured.err


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
        body = b'{"healthy": true, "version": "1.18.15"}'
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
        OpenCodeRuntimeConfig(
            service=OpenCodeConfig(
                server_url=HttpUrl(f"http://127.0.0.1:{unused_tcp_port}"),
                request_timeout_seconds=1,
                executable=executable,
                config_file=tmp_path / "isolated-config" / "opencode" / "opencode.json",
                xdg_config_home=tmp_path / "isolated-config",
                xdg_data_home=tmp_path / "isolated-data",
                startup_timeout_seconds=5,
                shutdown_timeout_seconds=1,
            ),
            password="ephemeral",
            execution_timeout_seconds=3,
            process_path="/usr/bin:/bin",
            process_lang="C.UTF-8",
        )
    )

    # WHEN
    started_at = time.monotonic()
    await client.start()

    # THEN
    assert time.monotonic() - started_at >= 1
    await client.close()
