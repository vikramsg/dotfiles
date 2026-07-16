import asyncio
import base64
from collections.abc import AsyncIterator, Mapping
from pathlib import Path
from urllib.parse import quote

import aiohttp
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from ocint.daemon.models import PromptObservation, RuntimeEvent, RuntimeMessage, RuntimePart, RuntimeSession


class OpenCodeSessionResponse(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    id: str
    title: str = ""


class OpenCodePartResponse(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    type: str
    text: str = ""


class OpenCodeMessageInfo(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    id: str = ""
    role: str = "unknown"


class OpenCodeMessageResponse(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    info: OpenCodeMessageInfo = Field(default_factory=OpenCodeMessageInfo)
    parts: list[OpenCodePartResponse] = Field(default_factory=list)


class OpenCodeStatusResponse(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    type: str = "idle"


class OpenCodeHealthResponse(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    healthy: bool = True
    version: str = ""


class OpenCodeEventStatus(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    type: str = ""


class OpenCodeEventProperties(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True, frozen=True)

    session_id_upper: str = Field(default="", alias="sessionID")
    session_id_lower: str = Field(default="", alias="sessionId")
    status: OpenCodeEventStatus = Field(default_factory=OpenCodeEventStatus)

    def session_id(self) -> str:
        return self.session_id_upper or self.session_id_lower


class OpenCodeEventPayload(BaseModel):
    model_config = ConfigDict(extra="allow", frozen=True)

    type: str
    properties: OpenCodeEventProperties = Field(default_factory=OpenCodeEventProperties)


class OpenCodeGlobalEnvelope(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    directory: str = ""
    payload: OpenCodeEventPayload


class OpenCodeRuntime:
    def __init__(
        self,
        server_url: str,
        username: str,
        password: str,
        timeout_seconds: int,
        expected_version: str = "1.17.20",
    ) -> None:
        self.server_url = server_url.rstrip("/")
        encoded = base64.b64encode(f"{username}:{password}".encode()).decode()
        self.headers = {"Authorization": f"Basic {encoded}"} if password else {}
        self.timeout = aiohttp.ClientTimeout(total=timeout_seconds)
        self.expected_version = expected_version
        self.client: aiohttp.ClientSession | None = None

    async def start(self) -> None:
        if self.client is None:
            self.client = aiohttp.ClientSession(headers=self.headers, timeout=self.timeout)

    async def health(self) -> None:
        client = self._client()
        async with client.get(f"{self.server_url}/global/health") as response:
            await self._raise(response)
            health = OpenCodeHealthResponse.model_validate(await response.json())
            if not health.healthy:
                raise RuntimeError("OpenCode health check reported unhealthy")
            if health.version != self.expected_version:
                raise RuntimeError(
                    f"OpenCode version mismatch: expected {self.expected_version}, received {health.version or 'unknown'}"
                )

    async def close(self) -> None:
        if self.client is not None:
            await self.client.close()
            self.client = None

    async def create(self, directory: Path, identity: str) -> RuntimeSession:
        headers = self._headers(directory)
        async with self._client().get(f"{self.server_url}/session", headers=headers) as response:
            await self._raise(response)
            sessions = TypeAdapter(list[OpenCodeSessionResponse]).validate_python(await response.json())
        for session in sessions:
            if session.title == identity:
                return RuntimeSession(session_id=session.id, status="idle")
        async with self._client().post(
            f"{self.server_url}/session", json={"title": identity}, headers=headers
        ) as response:
            await self._raise(response)
            payload = OpenCodeSessionResponse.model_validate(await response.json())
            return RuntimeSession(session_id=payload.id, status="idle")

    async def has_prompt(self, directory: Path, session_id: str, text: str) -> bool:
        return (await self.prompt_observation(directory, session_id, text)).found

    async def prompt_observation(self, directory: Path, session_id: str, text: str) -> PromptObservation:
        async with self._client().get(
            f"{self.server_url}/session/{quote(session_id, safe='')}/message", headers=self._headers(directory)
        ) as response:
            await self._raise(response)
            messages = TypeAdapter(list[OpenCodeMessageResponse]).validate_python(await response.json())
            found_at = next(
                (
                    index
                    for index, message in enumerate(messages)
                    if any(part.type == "text" and part.text == text for part in message.parts)
                ),
                None,
            )
            completed = found_at is not None and any(
                message.info.role == "assistant" and message.parts for message in messages[found_at + 1 :]
            )
            return PromptObservation(found=found_at is not None, completed=completed)

    async def messages(self, directory: Path, session_id: str) -> list[RuntimeMessage]:
        async with self._client().get(
            f"{self.server_url}/session/{quote(session_id, safe='')}/message", headers=self._headers(directory)
        ) as response:
            await self._raise(response)
            messages = TypeAdapter(list[OpenCodeMessageResponse]).validate_python(await response.json())
            return [
                RuntimeMessage(
                    message_id=message.info.id or str(index),
                    role=message.info.role,
                    parts=[RuntimePart(part_type=part.type, text=part.text) for part in message.parts],
                )
                for index, message in enumerate(messages)
            ]

    async def prompt(self, directory: Path, session_id: str, text: str) -> None:
        payload = {"parts": [{"type": "text", "text": text}]}
        async with self._client().post(
            f"{self.server_url}/session/{quote(session_id, safe='')}/prompt_async",
            json=payload,
            headers=self._headers(directory),
        ) as response:
            await self._raise(response)

    async def inspect(self, directory: Path, session_id: str) -> RuntimeSession:
        async with self._client().get(
            f"{self.server_url}/session/status", headers=self._headers(directory)
        ) as response:
            await self._raise(response)
            statuses = TypeAdapter(Mapping[str, OpenCodeStatusResponse]).validate_python(await response.json())
            status = statuses.get(session_id, OpenCodeStatusResponse()).type
            return RuntimeSession(session_id=session_id, status=status)

    async def events(self, directory: Path, session_id: str) -> AsyncIterator[RuntimeEvent]:
        timeout = aiohttp.ClientTimeout(total=None, sock_connect=self.timeout.total, sock_read=None)
        expected_directory = str(directory.resolve())
        while True:
            try:
                async with self._client().get(
                    f"{self.server_url}/global/event",
                    headers={"Accept": "text/event-stream"},
                    timeout=timeout,
                ) as response:
                    await self._raise(response)
                    async for raw_line in response.content:
                        line = raw_line.decode().strip()
                        if not line.startswith("data:"):
                            continue
                        envelope = OpenCodeGlobalEnvelope.model_validate_json(line.removeprefix("data:").strip())
                        if envelope.directory and str(Path(envelope.directory).resolve()) != expected_directory:
                            continue
                        if not envelope.directory and envelope.payload.type != "server.connected":
                            continue
                        event_session = envelope.payload.properties.session_id()
                        if event_session and event_session != session_id:
                            continue
                        event = RuntimeEvent(
                            event_type=envelope.payload.type,
                            session_id=event_session or session_id,
                            payload=envelope.model_dump_json(by_alias=True),
                            status=envelope.payload.properties.status.type,
                        )
                        yield event
                        if event.event_type == "session.idle" or (
                            event.event_type == "session.status" and event.status == "idle"
                        ):
                            return
            except aiohttp.ClientError:
                await asyncio.sleep(0.5)
                continue
            await asyncio.sleep(0.5)

    async def cancel(self, directory: Path, session_id: str) -> None:
        async with self._client().post(
            f"{self.server_url}/session/{quote(session_id, safe='')}/abort", headers=self._headers(directory)
        ) as response:
            await self._raise(response)

    async def dispose(self, directory: Path) -> None:
        async with self._client().post(
            f"{self.server_url}/instance/dispose", json={}, headers=self._headers(directory)
        ) as response:
            if response.status in {404, 410}:
                return
            await self._raise(response)

    def _client(self) -> aiohttp.ClientSession:
        if self.client is None or self.client.closed:
            raise RuntimeError("OpenCode runtime is not started")
        return self.client

    def _headers(self, directory: Path) -> Mapping[str, str]:
        return {"x-opencode-directory": str(directory.resolve()), "Content-Type": "application/json"}

    async def _raise(self, response: aiohttp.ClientResponse) -> None:
        if response.status >= 400:
            body = await response.text()
            raise RuntimeError(f"OpenCode HTTP {response.status}: {body[:500]}")
