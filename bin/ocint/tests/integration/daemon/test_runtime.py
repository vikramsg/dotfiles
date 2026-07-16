import socket
from pathlib import Path

import pytest
from aiohttp import web
from ocint.daemon.runtime import OpenCodeRuntime


@pytest.mark.asyncio
async def test_opencode_runtime_uses_real_http_and_sse_protocol(tmp_path: Path) -> None:
    # GIVEN a stateful local server implementing the OpenCode 1.17.20 protocol
    state: list[str] = []
    event_connections: list[int] = []
    dispose_calls: list[int] = []
    directory = tmp_path / "space & #brackets[]"
    directory.mkdir()

    async def create(request: web.Request) -> web.Response:
        state.append(f"create:{request.headers['x-opencode-directory']}")
        payload = await request.json()
        return web.json_response({"id": "ses_real", "title": payload["title"]}, status=201)

    async def sessions(_request: web.Request) -> web.Response:
        return web.json_response([])

    async def messages(_request: web.Request) -> web.Response:
        return web.json_response(
            [{"info": {"id": "msg-1", "role": "assistant"}, "parts": [{"type": "text", "text": "done"}]}]
        )

    async def health(_request: web.Request) -> web.Response:
        return web.json_response({"healthy": True, "version": "1.17.20"})

    async def dispose(_request: web.Request) -> web.Response:
        dispose_calls.append(1)
        return web.Response(status=200 if len(dispose_calls) == 1 else 404)

    async def prompt(request: web.Request) -> web.Response:
        payload = await request.json()
        state.append(f"prompt:{request.match_info['session_id']}:{payload['parts'][0]['text']}")
        return web.Response(status=204)

    async def status(_request: web.Request) -> web.Response:
        return web.json_response({"ses_real": {"type": "busy"}})

    async def events(_request: web.Request) -> web.StreamResponse:
        response = web.StreamResponse(headers={"Content-Type": "text/event-stream"})
        await response.prepare(_request)
        event_connections.append(1)
        await response.write(b'data: {"payload":{"type":"server.connected","properties":{}}}\n\n')
        if len(event_connections) == 1:
            await response.write_eof()
            return response
        wrong = b'data: {"directory":"/wrong","payload":{"type":"session.status","properties":{"status":{"type":"idle"}}}}\n\n'
        await response.write(wrong)
        await response.write(
            f'data: {{"directory":"{directory}","payload":{{"type":"session.status","properties":{{"sessionID":"ses_real","status":{{"type":"idle"}}}}}}}}\n\n'.encode()
        )
        await response.write_eof()
        return response

    application = web.Application()
    application.add_routes(
        [
            web.post("/session", create),
            web.get("/session", sessions),
            web.get("/session/{session_id}/message", messages),
            web.post("/session/{session_id}/prompt_async", prompt),
            web.get("/session/status", status),
            web.get("/global/event", events),
            web.get("/global/health", health),
            web.post("/instance/dispose", dispose),
        ]
    )
    runner = web.AppRunner(application)
    await runner.setup()
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    site = web.SockSite(runner, listener)
    await site.start()
    port = listener.getsockname()[1]
    runtime = OpenCodeRuntime(f"http://127.0.0.1:{port}", "opencode", "", 5)

    # WHEN a real client creates, prompts, inspects, and streams the session
    await runtime.start()
    await runtime.health()
    session = await runtime.create(directory, "ocint:test")
    assert await runtime.has_prompt(directory, session.session_id, "deterministic prompt") is False
    await runtime.prompt(directory, session.session_id, "deterministic prompt")
    inspected = await runtime.inspect(directory, session.session_id)
    received = [event.event_type async for event in runtime.events(directory, session.session_id)]
    messages_result = await runtime.messages(directory, session.session_id)
    await runtime.dispose(directory)
    await runtime.dispose(directory)

    # THEN directory routing, asynchronous prompt shape, status, and SSE are honored
    assert state == [f"create:{directory}", "prompt:ses_real:deterministic prompt"]
    assert inspected.status == "busy"
    assert received == ["server.connected", "server.connected", "session.status"]
    assert len(event_connections) == 2
    assert messages_result[0].role == "assistant"
    assert len(dispose_calls) == 2
    await runtime.close()
    assert runtime.client is None
    await runner.cleanup()
