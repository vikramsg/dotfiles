import asyncio
import base64
import json
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import quote

import aiohttp
from pydantic import BaseModel, ConfigDict, Field, JsonValue, TypeAdapter

from ocint.daemon.logging import get_logger
from ocint.daemon.models import PromptObservation
from ocint.daemon.opencode import (
    OpenCodeAdapterError,
    OpenCodePrompt,
    OpenCodeResponse,
    RetryableOpenCodeError,
    TerminalOpenCodeError,
)
from ocint.daemon.opencode.config import OpenCodeRuntimeConfig


class SessionPayload(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)
    id: str
    title: str = ""


class PartPayload(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)
    type: str
    text: str = ""


class ErrorDataPayload(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True, populate_by_name=True)

    message: str
    is_retryable: bool = Field(alias="isRetryable")


class ErrorPayload(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    name: str
    data: ErrorDataPayload


class MessageInfo(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True, populate_by_name=True)
    id: str = ""
    role: str = "unknown"
    parent_id: str = Field(default="", alias="parentID")
    finish: str | None = None
    error: ErrorPayload | None = None


class MessagePayload(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)
    info: MessageInfo = Field(default_factory=MessageInfo)
    parts: tuple[PartPayload, ...] = Field(default_factory=tuple)


class HealthPayload(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)
    healthy: bool = True
    version: str = ""


class StatusPayload(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)
    type: str = "idle"


class OpenCodePromptState(BaseModel):
    model_config = ConfigDict(frozen=True)
    observation: PromptObservation
    error: ErrorPayload | None = None
    response: OpenCodeResponse | None = None


class OpenCodeClient:
    def __init__(
        self,
        config: OpenCodeRuntimeConfig,
    ) -> None:
        self.logger = get_logger("opencode")
        service = config.service
        self.server_url = str(service.server_url).rstrip("/")
        self.username = service.username
        self.password = config.password
        token = base64.b64encode(f"{self.username}:{self.password}".encode()).decode()
        self.headers = {"Authorization": f"Basic {token}"}
        self.request_timeout = aiohttp.ClientTimeout(total=service.request_timeout_seconds)
        self.request_timeout_seconds = service.request_timeout_seconds
        self.execution_timeout_seconds = config.execution_timeout_seconds
        self.expected_version = service.expected_version
        self.executable = service.executable
        self.config_file = service.config_file
        self.xdg_config_home = service.xdg_config_home
        self.xdg_data_home = service.xdg_data_home
        self.startup_timeout_seconds = service.startup_timeout_seconds
        self.shutdown_timeout_seconds = service.shutdown_timeout_seconds
        self.process_path = config.process_path
        self.process_lang = config.process_lang
        self.client: aiohttp.ClientSession | None = None
        self.process: asyncio.subprocess.Process | None = None

    async def start(self) -> None:
        port = self.server_url.rsplit(":", maxsplit=1)[-1]
        isolated_home = self.xdg_config_home / "home"
        isolated_state = self.xdg_config_home / "state"
        isolated_cache = self.xdg_config_home / "cache"
        for path in (isolated_home, isolated_state, isolated_cache):
            path.mkdir(parents=True, exist_ok=True)
            path.chmod(0o700)
        self.process = await asyncio.create_subprocess_exec(
            *self.serve_arguments(port),
            env=self.child_environment(),
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
            start_new_session=True,
        )
        self.logger.info("OpenCode process started", pid=self.process.pid, server=self.server_url)
        self.client = aiohttp.ClientSession(headers=self.headers, timeout=self.request_timeout)
        try:
            async with asyncio.timeout(self.startup_timeout_seconds):
                while True:
                    if self.process.returncode is not None:
                        raise RuntimeError(f"OpenCode exited during startup ({self.process.returncode})")
                    try:
                        async with self.client.get(f"{self.server_url}/global/health") as response:
                            await self._raise(response)
                            health = HealthPayload.model_validate(await response.json())
                        break
                    except aiohttp.ClientError, RuntimeError, TimeoutError:
                        await asyncio.sleep(0.1)
        except TimeoutError:
            await self.close()
            raise RuntimeError("OpenCode did not become healthy before startup timeout") from None
        if not health.healthy or health.version != self.expected_version:
            await self.close()
            raise RuntimeError(
                f"OpenCode version mismatch: expected {self.expected_version}, received {health.version}"
            )
        self.logger.info("OpenCode process ready", pid=self.process.pid, version=health.version)

    def child_environment(self) -> Mapping[str, str]:
        config_home = self.xdg_config_home.expanduser().resolve()
        return {
            "HOME": str(config_home / "home"),
            "PATH": self.process_path,
            "LANG": self.process_lang,
            "OPENCODE_CONFIG": str(self.config_file.expanduser().resolve()),
            "XDG_CONFIG_HOME": str(config_home),
            "XDG_DATA_HOME": str(self.xdg_data_home.expanduser().resolve()),
            "XDG_STATE_HOME": str(config_home / "state"),
            "XDG_CACHE_HOME": str(config_home / "cache"),
            "OPENCODE_SERVER_PASSWORD": self.password,
            "OPENCODE_SERVER_USERNAME": self.username,
        }

    def serve_arguments(self, port: str) -> list[str]:
        return [
            str(self.executable),
            "serve",
            "--hostname",
            "127.0.0.1",
            "--port",
            port,
            "--pure",
        ]

    async def close(self) -> None:
        if self.client is not None:
            await self.client.close()
        if self.process is not None and self.process.returncode is None:
            self.process.terminate()
            try:
                async with asyncio.timeout(self.shutdown_timeout_seconds):
                    await self.process.wait()
            except TimeoutError:
                self.process.kill()
                await self.process.wait()
        if self.process is not None:
            self.logger.info("OpenCode process stopped", pid=self.process.pid, status=self.process.returncode)

    async def wait_exited(self) -> int:
        if self.process is None:
            raise RuntimeError("OpenCode process is not started")
        return await self.process.wait()

    async def create(self, directory: Path, identity: str) -> str:
        async with self._request("GET", f"{self.server_url}/session", headers=self._directory(directory)) as response:
            sessions = TypeAdapter(tuple[SessionPayload, ...]).validate_python(await response.json())
        existing = next((item for item in sessions if item.title == identity), None)
        if existing is not None:
            self.logger.info("OpenCode session reused", session=existing.id, directory=str(directory.resolve()))
            return existing.id
        async with self._request(
            "POST",
            f"{self.server_url}/session",
            headers=self._directory(directory),
            json_payload={"title": identity},
        ) as response:
            session = SessionPayload.model_validate(await response.json()).id
        self.logger.info("OpenCode session created", session=session, directory=str(directory.resolve()))
        return session

    async def observe_prompt(self, directory: Path, session_id: str, text: str) -> PromptObservation:
        state = await self._prompt_state(directory, session_id, text)
        self._raise_prompt_error(state.error, directory, session_id)
        return state.observation

    async def _prompt_state(self, directory: Path, session_id: str, text: str) -> OpenCodePromptState:
        messages = await self._messages(directory, session_id)
        found_at = self._managed_prompt_index(messages, text)
        assistant_completed = found_at is not None and self._terminal_assistant_after(messages, found_at)
        status = await self._status(directory, session_id)
        active = status not in {None, "idle"}
        completed = assistant_completed and not active
        error = self._assistant_error_after(messages, found_at) if found_at is not None and not active else None
        return OpenCodePromptState(
            observation=PromptObservation(found=found_at is not None, completed=completed, active=active),
            error=error,
        )

    async def observe_response(self, directory: Path, session_id: str, prompt: OpenCodePrompt) -> PromptObservation:
        state = await self._response_state(directory, session_id, prompt.message_id)
        self._raise_prompt_error(state.error, directory, session_id)
        return state.observation

    async def _response_state(self, directory: Path, session_id: str, message_id: str) -> OpenCodePromptState:
        messages = await self._messages(directory, session_id)
        found_at = self._message_index(messages, message_id)
        response_message = (
            self._terminal_response_after(messages, found_at, message_id) if found_at is not None else None
        )
        status = await self._status(directory, session_id)
        active = status not in {None, "idle"}
        response = self._response(response_message) if response_message is not None and not active else None
        error = (
            self._response_error_after(messages, found_at, message_id) if found_at is not None and not active else None
        )
        return OpenCodePromptState(
            observation=PromptObservation(found=found_at is not None, completed=response is not None, active=active),
            error=error,
            response=response,
        )

    async def prompt(self, directory: Path, session_id: str, text: str) -> None:
        async with self._request(
            "POST",
            f"{self.server_url}/session/{quote(session_id, safe='')}/prompt_async",
            headers=self._directory(directory),
            json_payload={"parts": [{"type": "text", "text": text}]},
        ) as response:
            await response.read()
        self.logger.info("OpenCode prompt submitted", session=session_id, directory=str(directory.resolve()))

    async def submit_prompt(self, directory: Path, session_id: str, prompt: OpenCodePrompt) -> None:
        async with self._request(
            "POST",
            f"{self.server_url}/session/{quote(session_id, safe='')}/prompt_async",
            headers=self._directory(directory),
            json_payload={"messageID": prompt.message_id, "parts": [{"type": "text", "text": prompt.text}]},
        ) as response:
            await response.read()
        self.logger.info(
            "OpenCode correlated prompt submitted",
            session=session_id,
            message=prompt.message_id,
            directory=str(directory.resolve()),
        )

    async def wait_for_completion(self, directory: Path, session_id: str, text: str) -> None:
        async def read_state() -> OpenCodePromptState:
            return await self._prompt_state(directory, session_id, text)

        await self._wait_for_terminal(directory, session_id, read_state)

    async def wait_for_response(self, directory: Path, session_id: str, prompt: OpenCodePrompt) -> OpenCodeResponse:
        async def read_state() -> OpenCodePromptState:
            return await self._response_state(directory, session_id, prompt.message_id)

        state = await self._wait_for_terminal(directory, session_id, read_state)
        if state.response is None:
            raise RuntimeError(f"OpenCode session {session_id} completed without a correlated assistant response")
        return state.response

    async def _wait_for_terminal(
        self,
        directory: Path,
        session_id: str,
        read_state: Callable[[], Awaitable[OpenCodePromptState]],
    ) -> OpenCodePromptState:
        try:
            async with asyncio.timeout(self.execution_timeout_seconds):
                while True:
                    state = await read_state()
                    self._raise_prompt_error(state.error, directory, session_id)
                    if state.observation.completed:
                        self.logger.info(
                            "OpenCode prompt completed", session=session_id, directory=str(directory.resolve())
                        )
                        return state
                    async for event_type, event_session, status in self._events(directory, session_id, read_state):
                        if event_session and event_session != session_id:
                            continue
                        if event_type.startswith("permission"):
                            raise TerminalOpenCodeError("OpenCode requested an unapproved permission")
                        if event_type == "session.idle" or (event_type == "session.status" and status == "idle"):
                            break
                    state = await read_state()
                    self._raise_prompt_error(state.error, directory, session_id)
                    if state.observation.completed:
                        self.logger.info(
                            "OpenCode prompt completed", session=session_id, directory=str(directory.resolve())
                        )
                        return state
                    await asyncio.sleep(0.1)
        except TimeoutError:
            raise RetryableOpenCodeError(
                f"OpenCode session {session_id} did not complete the submitted prompt"
            ) from None

    async def _events(
        self,
        directory: Path,
        session_id: str,
        read_state: Callable[[], Awaitable[OpenCodePromptState]],
    ) -> AsyncIterator[tuple[str, str, str]]:
        timeout = aiohttp.ClientTimeout(total=None, sock_connect=self.request_timeout_seconds, sock_read=None)
        expected_directory = str(directory.resolve())
        async with self._request(
            "GET",
            f"{self.server_url}/global/event",
            headers={"Accept": "text/event-stream"},
            timeout=timeout,
        ) as response:
            if (await read_state()).observation.completed:
                yield ("session.idle", session_id, "idle")
                return
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

    async def _status(self, directory: Path, session_id: str) -> str | None:
        async with self._request(
            "GET", f"{self.server_url}/session/status", headers=self._directory(directory)
        ) as response:
            statuses = TypeAdapter(Mapping[str, StatusPayload]).validate_python(await response.json())
        status = statuses.get(session_id)
        return status.type if status is not None else None

    async def _messages(self, directory: Path, session_id: str) -> tuple[MessagePayload, ...]:
        async with self._request(
            "GET",
            f"{self.server_url}/session/{quote(session_id, safe='')}/message",
            headers=self._directory(directory),
        ) as response:
            return TypeAdapter(tuple[MessagePayload, ...]).validate_python(await response.json())

    def _managed_prompt_index(self, messages: tuple[MessagePayload, ...], text: str) -> int | None:
        latest_user = next(
            (index for index in range(len(messages) - 1, -1, -1) if messages[index].info.role == "user"),
            None,
        )
        if latest_user is None:
            return None
        message = messages[latest_user]
        return (
            latest_user
            if len(message.parts) == 1 and message.parts[0].type == "text" and message.parts[0].text == text
            else None
        )

    @staticmethod
    def _message_index(messages: tuple[MessagePayload, ...], message_id: str) -> int | None:
        return next(
            (
                index
                for index in range(len(messages) - 1, -1, -1)
                if messages[index].info.role == "user" and messages[index].info.id == message_id
            ),
            None,
        )

    @staticmethod
    def _terminal_response_after(
        messages: tuple[MessagePayload, ...], found_at: int, parent_id: str
    ) -> MessagePayload | None:
        return next(
            (
                message
                for message in messages[found_at + 1 :]
                if message.info.role == "assistant"
                and message.info.parent_id == parent_id
                and bool(message.info.id)
                and bool(message.info.finish)
                and message.info.finish not in {"tool-calls", "unknown"}
                and message.info.error is None
            ),
            None,
        )

    @staticmethod
    def _response(message: MessagePayload) -> OpenCodeResponse:
        return OpenCodeResponse(
            assistant_message_id=message.info.id,
            parent_message_id=message.info.parent_id,
            text="".join(part.text for part in message.parts if part.type == "text"),
        )

    @staticmethod
    def _response_error_after(
        messages: tuple[MessagePayload, ...], found_at: int, parent_id: str
    ) -> ErrorPayload | None:
        return next(
            (
                message.info.error
                for message in reversed(messages[found_at + 1 :])
                if message.info.role == "assistant"
                and message.info.parent_id == parent_id
                and message.info.error is not None
            ),
            None,
        )

    def _terminal_assistant_after(self, messages: tuple[MessagePayload, ...], found_at: int) -> bool:
        return any(
            message.info.role == "assistant"
            and bool(message.info.finish)
            and message.info.finish not in {"tool-calls", "unknown"}
            and message.info.error is None
            for message in messages[found_at + 1 :]
        )

    @staticmethod
    def _assistant_error_after(messages: tuple[MessagePayload, ...], found_at: int) -> ErrorPayload | None:
        return next(
            (
                message.info.error
                for message in reversed(messages[found_at + 1 :])
                if message.info.role == "assistant" and message.info.error is not None
            ),
            None,
        )

    def _raise_prompt_error(self, error: ErrorPayload | None, directory: Path, session_id: str) -> None:
        if error is None:
            return
        message = error.data.message.strip()[:500] or "OpenCode assistant failed"
        self.logger.error(
            "OpenCode prompt failed",
            session=session_id,
            directory=str(directory.resolve()),
            error_type=error.name,
            retryable=error.data.is_retryable,
        )
        error_type = RetryableOpenCodeError if error.data.is_retryable else TerminalOpenCodeError
        raise error_type(f"OpenCode session {session_id} failed: {error.name}: {message}")

    def _directory(self, directory: Path) -> dict[str, str]:
        return {"x-opencode-directory": str(directory.resolve()), "Content-Type": "application/json"}

    @asynccontextmanager
    async def _request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        json_payload: JsonValue | None = None,
        timeout: aiohttp.ClientTimeout | None = None,
    ) -> AsyncIterator[aiohttp.ClientResponse]:
        try:
            async with self._client().request(
                method,
                url,
                headers=headers,
                json=json_payload,
                timeout=timeout or self.request_timeout,
            ) as response:
                await self._raise(response)
                yield response
        except OpenCodeAdapterError:
            raise
        except (aiohttp.ClientError, TimeoutError) as error:
            raise RetryableOpenCodeError("OpenCode request failed temporarily") from error

    async def _raise(self, response: aiohttp.ClientResponse) -> None:
        if response.status >= 500:
            raise RetryableOpenCodeError(f"OpenCode HTTP {response.status}")
        if response.status >= 400:
            raise TerminalOpenCodeError(f"OpenCode HTTP {response.status}")
