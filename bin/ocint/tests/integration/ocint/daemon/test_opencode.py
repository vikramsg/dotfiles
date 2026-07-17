import asyncio
import base64
from dataclasses import dataclass, field
from pathlib import Path

import pytest
from aiohttp import web
from ocint.daemon.opencode import OpenCodeClient


@dataclass
class OpenCodeServer:
    directory: Path
    status: str = "busy"
    idle_event_connection: int = 1
    messages: list[dict[str, object]] = field(default_factory=list)
    authorization: str = ""
    directories: list[str] = field(default_factory=list)
    prompt: str = ""
    event_connections: int = 0
    status_checks: int = 0
    completion_delay_seconds: float | None = None
    completion_event: asyncio.Event = field(default_factory=asyncio.Event)
    completion_task: asyncio.Task[None] | None = None
    runner: web.AppRunner | None = None

    async def start(self, port: int) -> None:
        async def health(request: web.Request) -> web.Response:
            self.authorization = request.headers.get("Authorization", "")
            return web.json_response({"healthy": True, "version": "1.17.20"})

        async def sessions(request: web.Request) -> web.Response:
            self.directories.append(request.headers.get("x-opencode-directory", ""))
            if request.method == "GET":
                return web.json_response([])
            return web.json_response({"id": "session", "title": (await request.json())["title"]})

        async def messages(_request: web.Request) -> web.Response:
            return web.json_response(self.messages)

        async def prompt(request: web.Request) -> web.Response:
            self.prompt = (await request.json())["parts"][0]["text"]
            if self.completion_delay_seconds is not None:
                self.messages = [{"info": {"role": "user"}, "parts": [{"type": "text", "text": self.prompt}]}]

                async def complete() -> None:
                    await asyncio.sleep(self.completion_delay_seconds or 0)
                    (self.directory / "result.txt").write_text("completed\n")
                    self.messages.append(
                        {
                            "info": {"role": "assistant", "finish": "stop"},
                            "parts": [{"type": "text", "text": "done"}],
                        }
                    )
                    self.completion_event.set()

                self.completion_task = asyncio.create_task(complete())
            else:
                self.messages = [
                    {"info": {"role": "user"}, "parts": [{"type": "text", "text": self.prompt}]},
                    {
                        "info": {"role": "assistant", "finish": "stop"},
                        "parts": [{"type": "text", "text": "done"}],
                    },
                ]
            return web.json_response({})

        async def status(_request: web.Request) -> web.Response:
            self.status_checks += 1
            return web.json_response({} if self.status == "idle" else {"session": {"type": self.status}})

        async def events(request: web.Request) -> web.StreamResponse:
            self.event_connections += 1
            response = web.StreamResponse(headers={"Content-Type": "text/event-stream"})
            await response.prepare(request)
            if self.completion_delay_seconds is not None:
                await self.completion_event.wait()
            if self.event_connections == self.idle_event_connection:
                payload = f'data: {{"directory":"{self.directory}","payload":{{"type":"session.idle","properties":{{"sessionID":"session"}}}}}}\n\n'
                await response.write(payload.encode())
            await response.write_eof()
            return response

        app = web.Application()
        app.router.add_get("/global/health", health)
        app.router.add_get("/session", sessions)
        app.router.add_post("/session", sessions)
        app.router.add_get("/session/{identifier}/message", messages)
        app.router.add_post("/session/{identifier}/prompt_async", prompt)
        app.router.add_get("/session/status", status)
        app.router.add_get("/global/event", events)
        self.runner = web.AppRunner(app)
        await self.runner.setup()
        await web.TCPSite(self.runner, "127.0.0.1", port).start()

    async def close(self) -> None:
        if self.runner is not None:
            await self.runner.cleanup()


@pytest.mark.asyncio
async def test_http_and_sse_match_opencode_contract(tmp_path: Path, unused_tcp_port: int) -> None:
    # GIVEN
    server = OpenCodeServer(tmp_path)
    await server.start(unused_tcp_port)
    client = OpenCodeClient(f"http://127.0.0.1:{unused_tcp_port}", "opencode", "password", 5, "1.17.20")

    # WHEN
    await client.start()
    session = await client.create(tmp_path, "ocint:job")
    observation = await client.observe_prompt(tmp_path, session, "work")
    await client.prompt(tmp_path, session, "work")
    await client.wait_idle(tmp_path, session)

    # THEN
    expected = base64.b64encode(b"opencode:password").decode()
    assert server.authorization == f"Basic {expected}"
    assert server.directories == [str(tmp_path.resolve()), str(tmp_path.resolve())]
    assert not observation.found
    assert server.prompt == "work"
    await client.close()
    await server.close()


@pytest.mark.asyncio
async def test_premature_sse_eof_while_busy_fails_bounded_wait(tmp_path: Path, unused_tcp_port: int) -> None:
    # GIVEN
    server = OpenCodeServer(tmp_path, idle_event_connection=1000)
    await server.start(unused_tcp_port)
    client = OpenCodeClient(f"http://127.0.0.1:{unused_tcp_port}", "opencode", "password", 1, "1.17.20")
    await client.start()
    await client.observe_prompt(tmp_path, "session", "work")

    # WHEN / THEN
    with pytest.raises(RuntimeError, match="did not become idle"):
        await client.wait_idle(tmp_path, "session")
    assert server.event_connections > 1
    await client.close()
    await server.close()


@pytest.mark.asyncio
async def test_sse_reconnect_waits_for_idle_event(tmp_path: Path, unused_tcp_port: int) -> None:
    # GIVEN
    server = OpenCodeServer(
        tmp_path,
        idle_event_connection=2,
        messages=[
            {"info": {"role": "user"}, "parts": [{"type": "text", "text": "work"}]},
            {
                "info": {"role": "assistant", "finish": "tool-calls"},
                "parts": [{"type": "tool", "text": ""}],
            },
            {
                "info": {"role": "assistant", "finish": "stop"},
                "parts": [{"type": "text", "text": "done"}],
            },
        ],
    )
    await server.start(unused_tcp_port)
    client = OpenCodeClient(f"http://127.0.0.1:{unused_tcp_port}", "opencode", "password", 2, "1.17.20")
    await client.start()
    observation = await client.observe_prompt(tmp_path, "session", "work")

    # WHEN
    await client.wait_idle(tmp_path, "session")

    # THEN
    assert not observation.completed
    assert server.event_connections == 2
    await client.close()
    await server.close()


@pytest.mark.asyncio
async def test_assistant_parts_do_not_complete_a_busy_session(tmp_path: Path, unused_tcp_port: int) -> None:
    # GIVEN
    server = OpenCodeServer(
        tmp_path,
        status="idle",
        messages=[
            {"info": {"role": "user"}, "parts": [{"type": "text", "text": "work"}]},
            {"info": {"role": "assistant"}, "parts": [{"type": "text", "text": "working"}]},
        ],
    )
    await server.start(unused_tcp_port)
    client = OpenCodeClient(f"http://127.0.0.1:{unused_tcp_port}", "opencode", "password", 2, "1.17.20")
    await client.start()

    # WHEN
    observation = await client.observe_prompt(tmp_path, "session", "work")

    # THEN
    assert observation.found
    assert not observation.completed
    await client.close()
    await server.close()


@pytest.mark.parametrize(
    ("assistant_info", "completed"),
    [
        ({"role": "assistant", "finish": "tool-calls"}, False),
        ({"role": "assistant", "finish": "unknown"}, False),
        (
            {
                "role": "assistant",
                "finish": "stop",
                "error": {
                    "name": "APIError",
                    "data": {"message": "provider failed", "isRetryable": False},
                },
            },
            False,
        ),
        ({"role": "assistant", "finish": "stop"}, True),
        ({"role": "assistant", "finish": "length"}, True),
    ],
)
@pytest.mark.asyncio
async def test_absent_status_requires_terminal_non_error_assistant_finish(
    tmp_path: Path, unused_tcp_port: int, assistant_info: dict[str, object], completed: bool
) -> None:
    # GIVEN
    server = OpenCodeServer(
        tmp_path,
        status="idle",
        messages=[
            {"info": {"role": "user"}, "parts": [{"type": "text", "text": "work"}]},
            {"info": assistant_info, "parts": [{"type": "text", "text": "response"}]},
        ],
    )
    await server.start(unused_tcp_port)
    client = OpenCodeClient(f"http://127.0.0.1:{unused_tcp_port}", "opencode", "password", 1, "1.17.20")
    await client.start()

    # WHEN
    observation = await client.observe_prompt(tmp_path, "session", "work")

    # THEN
    assert observation.completed is completed
    await client.close()
    await server.close()


@pytest.mark.asyncio
async def test_later_unmatched_user_turn_prevents_managed_prompt_completion(
    tmp_path: Path, unused_tcp_port: int
) -> None:
    # GIVEN
    server = OpenCodeServer(
        tmp_path,
        status="idle",
        messages=[
            {"info": {"role": "user"}, "parts": [{"type": "text", "text": "work"}]},
            {
                "info": {"role": "assistant", "finish": "stop"},
                "parts": [{"type": "text", "text": "done"}],
            },
            {"info": {"role": "user"}, "parts": [{"type": "text", "text": "unmanaged follow-up"}]},
        ],
    )
    await server.start(unused_tcp_port)
    client = OpenCodeClient(f"http://127.0.0.1:{unused_tcp_port}", "opencode", "password", 1, "1.17.20")
    await client.start()

    # WHEN
    observation = await client.observe_prompt(tmp_path, "session", "work")

    # THEN
    assert not observation.found
    assert not observation.completed
    await client.close()
    await server.close()


@pytest.mark.asyncio
async def test_wait_idle_requires_bound_managed_prompt(tmp_path: Path, unused_tcp_port: int) -> None:
    # GIVEN
    server = OpenCodeServer(tmp_path, status="idle")
    await server.start(unused_tcp_port)
    client = OpenCodeClient(f"http://127.0.0.1:{unused_tcp_port}", "opencode", "password", 1, "1.17.20")
    await client.start()

    # WHEN / THEN
    with pytest.raises(RuntimeError, match="managed prompt is not bound"):
        await client.wait_idle(tmp_path, "session")
    await client.close()
    await server.close()


@pytest.mark.asyncio
async def test_restart_absent_idle_status_with_assistant_evidence_skips_sse(
    tmp_path: Path, unused_tcp_port: int
) -> None:
    # GIVEN
    server = OpenCodeServer(
        tmp_path,
        status="idle",
        idle_event_connection=1000,
        messages=[
            {"info": {"role": "user"}, "parts": [{"type": "text", "text": "work"}]},
            {
                "info": {"role": "assistant", "finish": "stop"},
                "parts": [{"type": "text", "text": "done"}],
            },
        ],
    )
    await server.start(unused_tcp_port)
    client = OpenCodeClient(f"http://127.0.0.1:{unused_tcp_port}", "opencode", "password", 1, "1.17.20")
    await client.start()
    observation = await client.observe_prompt(tmp_path, "session", "work")

    # WHEN
    await client.wait_idle(tmp_path, "session")

    # THEN
    assert observation.completed
    assert server.event_connections == 0
    await client.close()
    await server.close()


@pytest.mark.asyncio
async def test_absent_status_after_prompt_waits_for_assistant_edit_and_idle_event(
    tmp_path: Path, unused_tcp_port: int
) -> None:
    # GIVEN
    server = OpenCodeServer(tmp_path, status="idle", completion_delay_seconds=0.05)
    await server.start(unused_tcp_port)
    client = OpenCodeClient(f"http://127.0.0.1:{unused_tcp_port}", "opencode", "password", 1, "1.17.20")
    await client.start()
    await client.prompt(tmp_path, "session", "work")
    assert not (tmp_path / "result.txt").exists()
    assert len(server.messages) == 1

    # WHEN
    await client.wait_idle(tmp_path, "session")

    # THEN
    assert (tmp_path / "result.txt").read_text() == "completed\n"
    assert len(server.messages) == 2
    assert server.status_checks >= 1
    assert server.event_connections == 1
    assert server.completion_task is not None
    await server.completion_task
    await client.close()
    await server.close()


@pytest.mark.asyncio
async def test_restart_observes_completed_prompt_when_idle_status_is_absent(
    tmp_path: Path, unused_tcp_port: int
) -> None:
    # GIVEN
    server = OpenCodeServer(
        tmp_path,
        status="idle",
        messages=[
            {"info": {"role": "user"}, "parts": [{"type": "text", "text": "work"}]},
            {
                "info": {"role": "assistant", "finish": "stop"},
                "parts": [{"type": "text", "text": "done"}],
            },
        ],
    )
    await server.start(unused_tcp_port)
    client = OpenCodeClient(f"http://127.0.0.1:{unused_tcp_port}", "opencode", "password", 1, "1.17.20")
    await client.start()

    # WHEN
    observation = await client.observe_prompt(tmp_path, "session", "work")

    # THEN
    assert observation.found
    assert observation.completed
    await client.close()
    await server.close()
