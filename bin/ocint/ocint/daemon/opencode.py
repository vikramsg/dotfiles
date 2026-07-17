import asyncio
import base64
import json
from collections.abc import AsyncIterator, Mapping
from pathlib import Path
from urllib.parse import quote

import aiohttp
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from ocint.daemon.service import PromptObservation


class SessionPayload(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)
    id: str
    title: str = ""


class PartPayload(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)
    type: str
    text: str = ""


class MessageInfo(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)
    role: str = "unknown"


class MessagePayload(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)
    info: MessageInfo = Field(default_factory=MessageInfo)
    parts: list[PartPayload] = Field(default_factory=list)


class HealthPayload(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)
    healthy: bool = True
    version: str = ""


class StatusPayload(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)
    type: str = "idle"


class OpenCodeClient:
    def __init__(
        self, server_url: str, username: str, password: str, timeout_seconds: int, expected_version: str
    ) -> None:
        self.server_url = server_url.rstrip("/")
        token = base64.b64encode(f"{username}:{password}".encode()).decode()
        self.headers = {"Authorization": f"Basic {token}"}
        self.timeout = aiohttp.ClientTimeout(total=timeout_seconds)
        self.timeout_seconds = timeout_seconds
        self.expected_version = expected_version
        self.client: aiohttp.ClientSession | None = None

    async def start(self) -> None:
        self.client = aiohttp.ClientSession(headers=self.headers, timeout=self.timeout)
        async with self.client.get(f"{self.server_url}/global/health") as response:
            await self._raise(response)
            health = HealthPayload.model_validate(await response.json())
        if not health.healthy or health.version != self.expected_version:
            raise RuntimeError(
                f"OpenCode version mismatch: expected {self.expected_version}, received {health.version}"
            )

    async def close(self) -> None:
        if self.client is not None:
            await self.client.close()

    async def create(self, directory: Path, identity: str) -> str:
        async with self._client().get(f"{self.server_url}/session", headers=self._directory(directory)) as response:
            await self._raise(response)
            sessions = TypeAdapter(list[SessionPayload]).validate_python(await response.json())
        existing = next((item for item in sessions if item.title == identity), None)
        if existing is not None:
            return existing.id
        async with self._client().post(
            f"{self.server_url}/session", headers=self._directory(directory), json={"title": identity}
        ) as response:
            await self._raise(response)
            return SessionPayload.model_validate(await response.json()).id

    async def observe_prompt(self, directory: Path, session_id: str, text: str) -> PromptObservation:
        async with self._client().get(
            f"{self.server_url}/session/{quote(session_id, safe='')}/message", headers=self._directory(directory)
        ) as response:
            await self._raise(response)
            messages = TypeAdapter(list[MessagePayload]).validate_python(await response.json())
        found_at = next(
            (
                index
                for index, message in enumerate(messages)
                if any(part.type == "text" and part.text == text for part in message.parts)
            ),
            None,
        )
        assistant_completed = found_at is not None and any(
            item.info.role == "assistant" and item.parts for item in messages[found_at + 1 :]
        )
        completed = assistant_completed and await self._status(directory, session_id) == "idle"
        return PromptObservation(found=found_at is not None, completed=completed)

    async def prompt(self, directory: Path, session_id: str, text: str) -> None:
        async with self._client().post(
            f"{self.server_url}/session/{quote(session_id, safe='')}/prompt_async",
            headers=self._directory(directory),
            json={"parts": [{"type": "text", "text": text}]},
        ) as response:
            await self._raise(response)

    async def wait_idle(self, directory: Path, session_id: str) -> None:
        try:
            async with asyncio.timeout(self.timeout_seconds):
                if await self._status(directory, session_id) == "idle":
                    return
                while True:
                    async for event_type, event_session, status in self._events(directory):
                        if event_session and event_session != session_id:
                            continue
                        if event_type == "session.idle" or (event_type == "session.status" and status == "idle"):
                            return
                        if event_type.startswith("permission"):
                            raise PermissionError("OpenCode requested an unapproved permission")
                    if await self._status(directory, session_id) == "idle":
                        return
                    await asyncio.sleep(0.1)
        except TimeoutError:
            raise RuntimeError(f"OpenCode session {session_id} did not become idle") from None

    async def _events(self, directory: Path) -> AsyncIterator[tuple[str, str, str]]:
        timeout = aiohttp.ClientTimeout(total=None, sock_connect=self.timeout.total, sock_read=None)
        expected_directory = str(directory.resolve())
        async with self._client().get(
            f"{self.server_url}/global/event", headers={"Accept": "text/event-stream"}, timeout=timeout
        ) as response:
            await self._raise(response)
            async for raw in response.content:
                line = raw.decode().strip()
                if not line.startswith("data:"):
                    continue
                payload = json.loads(line.removeprefix("data:").strip())
                event = payload.get("payload", {})
                event_directory = payload.get("directory", "")
                if event_directory and str(Path(event_directory).resolve()) != expected_directory:
                    continue
                if not event_directory and event.get("type") != "server.connected":
                    continue
                properties = event.get("properties", {})
                yield (
                    event.get("type", ""),
                    properties.get("sessionID", properties.get("sessionId", "")),
                    properties.get("status", {}).get("type", ""),
                )

    def _client(self) -> aiohttp.ClientSession:
        if self.client is None or self.client.closed:
            raise RuntimeError("OpenCode client is not started")
        return self.client

    async def _status(self, directory: Path, session_id: str) -> str:
        async with self._client().get(
            f"{self.server_url}/session/status", headers=self._directory(directory)
        ) as response:
            await self._raise(response)
            statuses = TypeAdapter(Mapping[str, StatusPayload]).validate_python(await response.json())
        status = statuses.get(session_id)
        return status.type if status is not None else "missing"

    def _directory(self, directory: Path) -> dict[str, str]:
        return {"x-opencode-directory": str(directory.resolve()), "Content-Type": "application/json"}

    async def _raise(self, response: aiohttp.ClientResponse) -> None:
        if response.status >= 400:
            raise RuntimeError(f"OpenCode HTTP {response.status}: {(await response.text())[:500]}")
