import asyncio
import socket
from collections.abc import Mapping

import pytest
from aiohttp import web
from ocint.daemon.channels import GitHubChannel, SlackSocketChannel
from ocint.daemon.git import GitHubPublisher
from ocint.daemon.models import JobState, WorkRequest, WorkUpdate


class DurableSubmissionFailure(RuntimeError):
    pass


class StatefulFailingSubmit:
    def __init__(self) -> None:
        self.attempts: list[WorkRequest] = []

    def __call__(self, request: WorkRequest) -> None:
        self.attempts.append(request)
        raise DurableSubmissionFailure("persistence unavailable")


@pytest.mark.asyncio
async def test_stateful_fake_github_is_idempotent_over_real_http() -> None:
    # GIVEN a stateful local GitHub REST server with no pull requests
    pulls: list[Mapping[str, str | int]] = []

    async def list_pulls(_request: web.Request) -> web.Response:
        return web.json_response(pulls)

    async def create_pull(request: web.Request) -> web.Response:
        payload = await request.json()
        pull = {"html_url": "http://github.local/pull/1", "number": 1, "head": payload["head"]}
        pulls.append(pull)
        return web.json_response(pull, status=201)

    application = web.Application()
    application.add_routes(
        [web.get("/repos/owner/repo/pulls", list_pulls), web.post("/repos/owner/repo/pulls", create_pull)]
    )
    runner = web.AppRunner(application)
    await runner.setup()
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    await web.SockSite(runner, listener).start()
    publisher = GitHubPublisher(f"http://127.0.0.1:{listener.getsockname()[1]}", "token")

    # WHEN publication is repeated after an ambiguous delivery
    first = await publisher.publish("owner/repo", "ocint/job", "main", "title", "body")
    second = await publisher.publish("owner/repo", "ocint/job", "main", "title", "body")

    # THEN the existing provider artifact is reused
    assert first == second
    assert len(pulls) == 1
    await runner.cleanup()


@pytest.mark.asyncio
async def test_stateful_fake_slack_uses_real_http_and_websocket() -> None:
    # GIVEN a stateful local Slack Socket Mode server
    acknowledgements: list[str] = []
    ports: list[int] = []

    async def open_socket(_request: web.Request) -> web.Response:
        return web.json_response({"ok": True, "url": f"ws://127.0.0.1:{ports[0]}/socket"})

    async def socket_mode(request: web.Request) -> web.WebSocketResponse:
        response = web.WebSocketResponse()
        await response.prepare(request)
        await response.send_json(
            {
                "envelope_id": "env-1",
                "payload": {
                    "event_id": "Ev1",
                    "team_id": "T1",
                    "event": {"channel": "C1", "user": "U1", "text": "fix it", "ts": "1.2"},
                },
            }
        )
        message = await response.receive_json()
        acknowledgements.append(message["envelope_id"])
        await response.receive()
        await response.close()
        return response

    application = web.Application()
    application.add_routes([web.post("/open", open_socket), web.get("/socket", socket_mode)])
    runner = web.AppRunner(application)
    await runner.setup()
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    await web.SockSite(runner, listener).start()
    port = listener.getsockname()[1]
    ports.append(port)
    accepted: list[WorkRequest] = []
    channel = SlackSocketChannel(
        "http://127.0.0.1",
        f"http://127.0.0.1:{port}/open",
        "token",
        {"C1": "repo"},
        accepted.append,
    )

    # WHEN the production adapter consumes one real WebSocket envelope
    channel_task = asyncio.create_task(channel.run())
    deadline = asyncio.get_running_loop().time() + 5
    while not acknowledgements and asyncio.get_running_loop().time() < deadline:
        await asyncio.sleep(0.01)

    # THEN it acknowledges transport delivery and normalizes the work
    assert acknowledgements == ["env-1"]
    request = accepted[0]
    assert request.idempotency_key == "slack:T1:Ev1"
    assert request.repository == "repo"
    channel_task.cancel()
    await asyncio.gather(channel_task, return_exceptions=True)
    await runner.cleanup()


@pytest.mark.asyncio
async def test_slack_socket_does_not_acknowledge_failed_durable_submission() -> None:
    # GIVEN a real Socket Mode server and an injected durable store that rejects the request
    acknowledgements: list[str] = []
    ports: list[int] = []

    async def open_socket(_request: web.Request) -> web.Response:
        return web.json_response({"ok": True, "url": f"ws://127.0.0.1:{ports[0]}/socket"})

    async def socket_mode(request: web.Request) -> web.WebSocketResponse:
        response = web.WebSocketResponse()
        await response.prepare(request)
        await response.send_json(
            {
                "envelope_id": "env-fail",
                "payload": {
                    "event_id": "Ev-fail",
                    "team_id": "T1",
                    "event": {"channel": "C1", "user": "U1", "text": "fix it", "ts": "1.2"},
                },
            }
        )
        message = await response.receive()
        if message.type is web.WSMsgType.TEXT:
            acknowledgements.append(str(message.data))
        return response

    application = web.Application()
    application.add_routes([web.post("/open", open_socket), web.get("/socket", socket_mode)])
    runner = web.AppRunner(application)
    await runner.setup()
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    await web.SockSite(runner, listener).start()
    ports.append(listener.getsockname()[1])
    rejecting_store = StatefulFailingSubmit()
    channel = SlackSocketChannel(
        "http://127.0.0.1",
        f"http://127.0.0.1:{ports[0]}/open",
        "token",
        {"C1": "repo"},
        rejecting_store,
    )

    # WHEN persistence fails before the adapter can acknowledge
    with pytest.raises(DurableSubmissionFailure):
        await channel.run()

    # THEN no Socket Mode acknowledgement was sent
    assert acknowledgements == []
    assert [request.idempotency_key for request in rejecting_store.attempts] == ["slack:T1:Ev-fail"]
    await runner.cleanup()


@pytest.mark.asyncio
async def test_github_channel_looks_up_and_updates_ambiguous_delivery() -> None:
    # GIVEN a stateful GitHub comment API
    comments: list[Mapping[str, str | int]] = []
    updates: list[int] = []

    async def list_comments(_request: web.Request) -> web.Response:
        return web.json_response(comments)

    async def create_comment(request: web.Request) -> web.Response:
        payload = await request.json()
        comment = {"id": 1, "body": payload["body"]}
        comments.append(comment)
        return web.json_response(comment, status=201)

    async def update_comment(request: web.Request) -> web.Response:
        payload = await request.json()
        comments[0] = {"id": 1, "body": payload["body"]}
        updates.append(1)
        return web.json_response(comments[0])

    application = web.Application()
    application.add_routes(
        [
            web.get("/repos/owner/repo/issues/7/comments", list_comments),
            web.post("/repos/owner/repo/issues/7/comments", create_comment),
            web.patch("/repos/owner/repo/issues/comments/1", update_comment),
        ]
    )
    runner = web.AppRunner(application)
    await runner.setup()
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    await web.SockSite(runner, listener).start()
    accepted: list[WorkRequest] = []
    channel = GitHubChannel(
        f"http://127.0.0.1:{listener.getsockname()[1]}",
        "token",
        "repo",
        "owner/repo",
        "ocint",
        30,
        accepted.append,
    )
    update = WorkUpdate(
        conversation_id="owner/repo#7",
        job_id="job-7",
        status=JobState.COMPLETED,
        message="completed",
    )

    # WHEN the same durable outbox delivery is retried after an ambiguous result
    await channel.publish(update, "delivery-7", "issue:7")
    await channel.publish(update, "delivery-7", "issue:7")

    # THEN the marker is looked up and the existing comment is updated instead of duplicated
    assert len(comments) == 1
    assert updates == [1]
    assert "ocint-delivery:delivery-7" in str(comments[0]["body"])
    await runner.cleanup()
