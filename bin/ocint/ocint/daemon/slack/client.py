from collections.abc import Mapping

import aiohttp
from pydantic import BaseModel, ConfigDict, JsonValue

from ocint.daemon.slack.models import SlackAuth, SlackHistory, SlackMessage, SlackPostedMessage


class SlackApiError(RuntimeError):
    def __init__(self, error: str, needed: str = "") -> None:
        super().__init__(error)
        self.error = error
        self.needed = needed


class SlackRetryableError(RuntimeError):
    def __init__(self, message: str, retry_after_seconds: int = 1) -> None:
        super().__init__(message)
        if retry_after_seconds <= 0:
            raise ValueError("Slack retry delay must be positive")
        self.retry_after_seconds = retry_after_seconds


class SlackRateLimited(SlackRetryableError):
    def __init__(self, retry_after_seconds: int) -> None:
        super().__init__(f"Slack rate limited; retry after {retry_after_seconds} seconds", retry_after_seconds)


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
        data = {
            "channel": channel,
            "text": text,
            "client_msg_id": client_msg_id,
            "unfurl_links": "false",
            "unfurl_media": "false",
        }
        if thread_ts:
            data["thread_ts"] = thread_ts
        return SlackPostedMessage.model_validate(await self._call("chat.postMessage", data))

    async def find_reply(self, channel: str, root_ts: str, client_msg_id: str) -> SlackMessage | None:
        cursor = ""
        while True:
            page = await self.replies(channel, root_ts, cursor)
            for message in page.messages.root:
                if message.client_msg_id == client_msg_id:
                    return message
            cursor = page.response_metadata.next_cursor
            if not cursor:
                return None

    async def add_reaction(self, channel: str, timestamp: str, name: str) -> None:
        try:
            await self._call("reactions.add", {"channel": channel, "timestamp": timestamp, "name": name})
        except SlackApiError as error:
            if error.error != "already_reacted":
                raise

    async def _call(self, method: str, data: Mapping[str, str] | None = None) -> JsonValue:
        try:
            async with self._session().post(f"{self.api_url}/{method}", data=data) as response:
                retry_after = self._retry_after(response.headers.get("Retry-After", ""))
                if response.status == 429:
                    raise SlackRateLimited(retry_after)
                if response.status >= 500:
                    raise SlackRetryableError(f"Slack HTTP {response.status}", retry_after)
                if response.status >= 400:
                    raise SlackApiError(f"http_{response.status}")
                scopes = response.headers.get("X-OAuth-Scopes", "")
                if scopes:
                    self.granted_scopes = frozenset(item.strip() for item in scopes.split(",") if item.strip())
                payload: JsonValue = await response.json()
                envelope = SlackEnvelope.model_validate(payload)
                if not envelope.ok:
                    if envelope.error in frozenset(
                        (
                            "fatal_error",
                            "internal_error",
                            "ratelimited",
                            "request_timeout",
                            "service_unavailable",
                            "temporarily_unavailable",
                        )
                    ):
                        raise SlackRetryableError(f"Slack Web API temporarily failed: {envelope.error}", retry_after)
                    raise SlackApiError(envelope.error, envelope.needed)
                return payload
        except (aiohttp.ClientConnectionError, aiohttp.ClientPayloadError, TimeoutError) as error:
            raise SlackRetryableError("Slack network request failed") from error

    @staticmethod
    def _retry_after(value: str) -> int:
        try:
            parsed = int(value)
        except ValueError:
            return 1
        return parsed if parsed > 0 else 1

    def _session(self) -> aiohttp.ClientSession:
        if self.client is None or self.client.closed:
            raise RuntimeError("Slack client is not started")
        return self.client
