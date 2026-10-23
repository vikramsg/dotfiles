import pytest
from aiohttp import web
from ocint.daemon.slack.client import SlackClient, SlackRateLimited


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
            headers={"X-OAuth-Scopes": "groups:history,chat:write,reactions:write"},
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
    assert client.granted_scopes == frozenset(("groups:history", "chat:write", "reactions:write"))
    assert history_requests == [
        {
            "channel": "C1",
            "oldest": "1753380000.123456",
            "cursor": "",
            "limit": "1",
            "inclusive": "true",
        }
    ]
