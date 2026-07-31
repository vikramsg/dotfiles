from collections.abc import Mapping

import aiohttp
from pydantic import BaseModel, ConfigDict, JsonValue

from ocint.daemon.slack.models import SlackAuth, SlackHistory, SlackPostedMessage


class SlackApiError(RuntimeError):
    def __init__(self, error: str, needed: str = "") -> None:
        super().__init__(error)
        self.error = error
        self.needed = needed


class SlackRateLimited(RuntimeError):
    def __init__(self, retry_after_seconds: int) -> None:
        super().__init__(f"Slack rate limited; retry after {retry_after_seconds} seconds")
        self.retry_after_seconds = retry_after_seconds


class SlackEnvelope(BaseModel):
    model_config = ConfigDict(extra="allow", frozen=True)
    ok: bool
    error: str = ""
    needed: str = ""


class SlackClient:
    def __init__(self, token: str, api_url: str = "https://slack.com/api", request_timeout_seconds: int = 10) -> None:
        self.api_url = api_url.rstrip("/")
        self.token = token
        self.client: aiohttp.ClientSession | None = None
        self.granted_scopes: frozenset[str] = frozenset()
        self.request_timeout_seconds = request_timeout_seconds

    async def start(self) -> None:
        self.client = aiohttp.ClientSession(
            headers={"Authorization": f"Bearer {self.token}"},
            timeout=aiohttp.ClientTimeout(total=self.request_timeout_seconds),
        )

    async def close(self) -> None:
        if self.client is not None:
            await self.client.close()

    async def auth_test(self) -> SlackAuth:
        return SlackAuth.model_validate(await self._call("auth.test"))

    async def history(self, channel: str, oldest: str = "", cursor: str = "", limit: int = 200) -> SlackHistory:
        parameters = {"channel": channel, "oldest": oldest, "cursor": cursor, "limit": str(limit)}
        if oldest:
            parameters["inclusive"] = "true"
        return SlackHistory.model_validate(await self._call("conversations.history", parameters))

    async def replies(self, channel: str, root_ts: str, cursor: str = "") -> SlackHistory:
        return SlackHistory.model_validate(
            await self._call(
                "conversations.replies", {"channel": channel, "ts": root_ts, "cursor": cursor, "limit": "200"}
            )
        )

    async def post_message(self, channel: str, thread_ts: str, text: str, client_msg_id: str) -> SlackPostedMessage:
        return SlackPostedMessage.model_validate(
            await self._call(
                "chat.postMessage",
                {"channel": channel, "thread_ts": thread_ts, "text": text, "client_msg_id": client_msg_id},
            )
        )

    async def add_reaction(self, channel: str, timestamp: str, name: str) -> None:
        try:
            await self._call("reactions.add", {"channel": channel, "timestamp": timestamp, "name": name})
        except SlackApiError as error:
            if error.error != "already_reacted":
                raise

    async def _call(self, method: str, data: Mapping[str, str] | None = None) -> JsonValue:
        async with self._session().post(f"{self.api_url}/{method}", data=data) as response:
            if response.status == 429:
                raise SlackRateLimited(int(response.headers.get("Retry-After", "1")))
            response.raise_for_status()
            scopes = response.headers.get("X-OAuth-Scopes", "")
            if scopes:
                self.granted_scopes = frozenset(item.strip() for item in scopes.split(",") if item.strip())
            payload: JsonValue = await response.json()
            envelope = SlackEnvelope.model_validate(payload)
            if not envelope.ok:
                raise SlackApiError(envelope.error, envelope.needed)
            return payload

    def _session(self) -> aiohttp.ClientSession:
        if self.client is None or self.client.closed:
            raise RuntimeError("Slack client is not started")
        return self.client
