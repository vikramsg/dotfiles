from pathlib import Path
from typing import Literal

import pytest
from aiohttp import web
from ocint.daemon.slack.client import SlackClient, SlackRateLimited, SlackRetryableError
from ocint.daemon.slack.models import SlackHistory
from pydantic import BaseModel, ConfigDict


class ContractPostResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    ok: Literal[True]
    ts: str


class ContractReplies(SlackHistory):
    model_config = ConfigDict(extra="ignore", frozen=True)
    ok: Literal[True]


class SlackContract(BaseModel):
    model_config = ConfigDict(frozen=True)
    client_msg_id: str
    chat_post_message: tuple[ContractPostResponse, ContractPostResponse]
    conversations_replies: ContractReplies


@pytest.mark.asyncio
async def test_client_surfaces_retry_after_without_unbounded_sleep(unused_tcp_port: int) -> None:
    # GIVEN
    attempts: list[str] = []
    history_requests: list[dict[str, str]] = []

    async def auth(request: web.Request) -> web.Response:
        attempts.append(request.headers.get("Authorization", ""))
        if len(attempts) == 1:
            return web.json_response({"ok": False, "error": "ratelimited"}, status=429, headers={"Retry-After": "7"})
        return web.json_response(
            {"ok": True, "user_id": "UBOT", "bot_id": "BBOT", "team_id": "T1"},
            headers={"X-OAuth-Scopes": "channels:history,chat:write,reactions:write"},
        )

    async def reaction(_request: web.Request) -> web.Response:
        return web.json_response({"ok": False, "error": "already_reacted"})

    async def history(request: web.Request) -> web.Response:
        payload = await request.post()
        history_requests.append({key: str(value) for key, value in payload.items()})
        return web.json_response({"ok": True, "messages": [], "response_metadata": {"next_cursor": ""}})

    app = web.Application()
    app.router.add_post("/auth.test", auth)
    app.router.add_post("/reactions.add", reaction)
    app.router.add_post("/conversations.history", history)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "127.0.0.1", unused_tcp_port).start()
    client = SlackClient("secret", f"http://127.0.0.1:{unused_tcp_port}")
    await client.start()

    # WHEN
    try:
        with pytest.raises(SlackRateLimited) as raised:
            await client.auth_test()
        identity = await client.auth_test()
        await client.add_reaction("C1", "1.000", "white_check_mark")
        await client.history("C1", "1753380000.123456", limit=1)
    finally:
        await client.close()
        await runner.cleanup()

    # THEN
    assert identity.user_id == "UBOT"
    assert raised.value.retry_after_seconds == 7
    assert attempts == ["Bearer secret", "Bearer secret"]
    assert client.granted_scopes == frozenset(("channels:history", "chat:write", "reactions:write"))
    assert history_requests == [
        {
            "channel": "C1",
            "oldest": "1753380000.123456",
            "cursor": "",
            "limit": "1",
            "inclusive": "true",
        }
    ]


@pytest.mark.asyncio
async def test_post_preserves_client_message_id_disables_unfurls_and_lookup_paginates(unused_tcp_port: int) -> None:
    # GIVEN
    posts: list[dict[str, str]] = []
    reply_cursors: list[str] = []

    async def post_message(request: web.Request) -> web.Response:
        payload = await request.post()
        posts.append({key: str(value) for key, value in payload.items()})
        return web.json_response({"ok": True, "ts": "1754000000.123456"})

    async def replies(request: web.Request) -> web.Response:
        payload = await request.post()
        cursor = str(payload["cursor"])
        reply_cursors.append(cursor)
        if not cursor:
            return web.json_response(
                {
                    "ok": True,
                    "messages": [{"ts": "1.000001", "client_msg_id": "other"}],
                    "response_metadata": {"next_cursor": "page-2"},
                }
            )
        return web.json_response(
            {
                "ok": True,
                "messages": [{"ts": "1.000002", "client_msg_id": "exact-uuid"}],
                "response_metadata": {"next_cursor": ""},
            }
        )

    app = web.Application()
    app.router.add_post("/chat.postMessage", post_message)
    app.router.add_post("/conversations.replies", replies)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "127.0.0.1", unused_tcp_port).start()
    client = SlackClient("secret", f"http://127.0.0.1:{unused_tcp_port}")
    await client.start()

    # WHEN
    try:
        posted = await client.post_message("C1", "1.000001", "reply", "exact-uuid")
        found = await client.find_reply("C1", "1.000001", "exact-uuid")
    finally:
        await client.close()
        await runner.cleanup()

    # THEN
    assert posted.ts == "1754000000.123456"
    assert found is not None
    assert found.ts == "1.000002"
    assert reply_cursors == ["", "page-2"]
    assert posts == [
        {
            "channel": "C1",
            "thread_ts": "1.000001",
            "text": "reply",
            "client_msg_id": "exact-uuid",
            "unfurl_links": "false",
            "unfurl_media": "false",
        }
    ]


@pytest.mark.asyncio
async def test_real_slack_contract_fixture_proves_duplicate_post_and_reply_lookup_behavior(
    unused_tcp_port: int,
) -> None:
    # GIVEN
    fixture = SlackContract.model_validate_json(
        (Path(__file__).parents[4] / "fixtures/contracts/slack-client-msg-id-deduplication.json").read_text()
    )
    responses = iter(fixture.chat_post_message)
    posts: list[str] = []
    thread_fields: list[bool] = []

    async def post_message(request: web.Request) -> web.Response:
        payload = await request.post()
        posts.append(str(payload["client_msg_id"]))
        thread_fields.append("thread_ts" in payload)
        return web.json_response(next(responses).model_dump(mode="json"))

    async def replies(_request: web.Request) -> web.Response:
        return web.json_response(fixture.conversations_replies.model_dump(mode="json"))

    app = web.Application()
    app.router.add_post("/chat.postMessage", post_message)
    app.router.add_post("/conversations.replies", replies)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "127.0.0.1", unused_tcp_port).start()
    client = SlackClient("secret", f"http://127.0.0.1:{unused_tcp_port}")
    await client.start()

    # WHEN
    try:
        first = await client.post_message("sanitized-channel", "", "probe", fixture.client_msg_id)
        second = await client.post_message("sanitized-channel", "", "probe", fixture.client_msg_id)
        found = await client.find_reply("sanitized-channel", first.ts, fixture.client_msg_id)
    finally:
        await client.close()
        await runner.cleanup()

    # THEN
    assert fixture.chat_post_message[0].ok
    assert fixture.chat_post_message[1].ok
    assert first.ts == second.ts == "1786102300.739099"
    assert posts == [fixture.client_msg_id, fixture.client_msg_id]
    assert thread_fields == [False, False]
    assert found is not None
    assert found.ts == first.ts
    assert found.client_msg_id == fixture.client_msg_id
    assert found.bot_id == "B0BKQ75PZK3"
    assert fixture.conversations_replies.response_metadata.next_cursor == ""


@pytest.mark.asyncio
async def test_http_5xx_preserves_retry_after_for_durable_retry(unused_tcp_port: int) -> None:
    # GIVEN
    async def post_message(_request: web.Request) -> web.Response:
        return web.Response(status=503, headers={"Retry-After": "13"})

    app = web.Application()
    app.router.add_post("/chat.postMessage", post_message)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "127.0.0.1", unused_tcp_port).start()
    client = SlackClient("secret", f"http://127.0.0.1:{unused_tcp_port}")
    await client.start()

    # WHEN
    try:
        with pytest.raises(SlackRetryableError) as raised:
            await client.post_message("C1", "1.000001", "reply", "exact-uuid")
    finally:
        await client.close()
        await runner.cleanup()

    # THEN
    assert raised.value.retry_after_seconds == 13


@pytest.mark.asyncio
async def test_network_failure_is_classified_for_durable_retry(unused_tcp_port: int) -> None:
    # GIVEN
    client = SlackClient("secret", f"http://127.0.0.1:{unused_tcp_port}")
    await client.start()

    # WHEN / THEN
    try:
        with pytest.raises(SlackRetryableError):
            await client.auth_test()
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_documented_transient_web_api_error_is_retryable(unused_tcp_port: int) -> None:
    # GIVEN
    async def auth(_request: web.Request) -> web.Response:
        return web.json_response({"ok": False, "error": "internal_error"})

    app = web.Application()
    app.router.add_post("/auth.test", auth)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "127.0.0.1", unused_tcp_port).start()
    client = SlackClient("secret", f"http://127.0.0.1:{unused_tcp_port}")
    await client.start()

    # WHEN / THEN
    try:
        with pytest.raises(SlackRetryableError, match="internal_error"):
            await client.auth_test()
    finally:
        await client.close()
        await runner.cleanup()
