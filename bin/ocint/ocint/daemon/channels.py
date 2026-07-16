import asyncio
import hashlib
import hmac
import time
from collections.abc import Callable, Mapping

import aiohttp
from pydantic import BaseModel, ConfigDict, TypeAdapter

from ocint.daemon.models import Job, WorkRequest, WorkSource, WorkUpdate


class ManualChannel:
    def __init__(self, submit: Callable[[WorkRequest], Job | None]) -> None:
        self.source = WorkSource.MANUAL
        self.adapter_id = "manual"
        self.queue: asyncio.Queue[WorkRequest | None] = asyncio.Queue()
        self.updates: list[WorkUpdate] = []
        self.delivery_keys: set[str] = set()
        self.submit = submit

    async def enqueue(self, request: WorkRequest) -> None:
        await self.queue.put(request)

    async def close(self) -> None:
        await self.queue.put(None)

    async def run(self) -> None:
        while True:
            request = await self.queue.get()
            if request is None:
                return
            self.submit(request)

    def accepts(self, delivery_target: str) -> bool:
        return delivery_target == "manual"

    async def publish(self, update: WorkUpdate, delivery_key: str, delivery_target: str) -> None:
        if not self.accepts(delivery_target):
            raise ValueError(f"manual channel cannot publish target: {delivery_target}")
        if delivery_key in self.delivery_keys:
            return
        self.delivery_keys.add(delivery_key)
        self.updates.append(update)


class ControlChannel:
    def __init__(self) -> None:
        self.source = WorkSource.WEB
        self.adapter_id = "control"
        self.updates: list[WorkUpdate] = []
        self.delivery_keys: set[str] = set()

    async def run(self) -> None:
        await asyncio.Event().wait()

    def accepts(self, delivery_target: str) -> bool:
        return delivery_target == "manual" or delivery_target.startswith("job:")

    async def publish(self, update: WorkUpdate, delivery_key: str, delivery_target: str) -> None:
        if not self.accepts(delivery_target):
            raise ValueError(f"control channel cannot publish target: {delivery_target}")
        if delivery_key in self.delivery_keys:
            return
        self.delivery_keys.add(delivery_key)
        self.updates.append(update)


class GitHubUser(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    login: str


class GitHubIssue(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    number: int
    title: str
    body: str = ""
    user: GitHubUser


class GitHubComment(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    id: int
    body: str


class GitHubChannel:
    def __init__(
        self,
        api_url: str,
        token: str,
        repository: str,
        github_repository: str,
        label: str,
        poll_seconds: float,
        submit: Callable[[WorkRequest], Job | None],
    ) -> None:
        self.source = WorkSource.GITHUB
        self.adapter_id = f"github:{repository}:{github_repository}"
        self.api_url = api_url.rstrip("/")
        self.token = token
        self.repository = repository
        self.github_repository = github_repository
        self.label = label
        self.poll_seconds = poll_seconds
        self.seen: set[int] = set()
        self.submit = submit

    async def run(self) -> None:
        while True:
            headers = {"Authorization": f"Bearer {self.token}", "Accept": "application/vnd.github+json"}
            async with (
                aiohttp.ClientSession(headers=headers) as client,
                client.get(
                    f"{self.api_url}/repos/{self.github_repository}/issues",
                    params={"labels": self.label, "state": "open"},
                ) as response,
            ):
                response.raise_for_status()
                issues = TypeAdapter(list[GitHubIssue]).validate_python(await response.json())
            for issue in issues:
                if issue.number in self.seen:
                    continue
                request = WorkRequest(
                    idempotency_key=f"github:{self.github_repository}:{issue.number}",
                    conversation_id=f"{self.github_repository}#{issue.number}",
                    actor=issue.user.login,
                    repository=self.repository,
                    text=f"{issue.title}\n\n{issue.body}".strip(),
                    source=WorkSource.GITHUB,
                    delivery_adapter=self.adapter_id,
                    delivery_target=f"issue:{issue.number}",
                    source_metadata={"issue_number": str(issue.number)},
                )
                self.submit(request)
                self.seen.add(issue.number)
            await asyncio.sleep(self.poll_seconds)

    def accepts(self, delivery_target: str) -> bool:
        return delivery_target.startswith("issue:")

    async def publish(self, update: WorkUpdate, delivery_key: str, delivery_target: str) -> None:
        if not self.accepts(delivery_target):
            raise ValueError(f"GitHub channel cannot publish target: {delivery_target}")
        number = delivery_target.rsplit(":", maxsplit=1)[-1]
        marker = f"<!-- ocint-delivery:{delivery_key} -->"
        body = update.message + (f"\n\n{update.artifact_url}" if update.artifact_url else "") + f"\n\n{marker}"
        headers = {"Authorization": f"Bearer {self.token}", "Accept": "application/vnd.github+json"}
        comments_url = f"{self.api_url}/repos/{self.github_repository}/issues/{number}/comments"
        async with aiohttp.ClientSession(headers=headers) as client:
            async with client.get(comments_url) as response:
                response.raise_for_status()
                comments = TypeAdapter(list[GitHubComment]).validate_python(await response.json())
            existing = next((comment for comment in comments if marker in comment.body), None)
            if existing is None:
                async with client.post(comments_url, json={"body": body}) as response:
                    response.raise_for_status()
            else:
                async with client.patch(
                    f"{self.api_url}/repos/{self.github_repository}/issues/comments/{existing.id}",
                    json={"body": body},
                ) as response:
                    response.raise_for_status()


class SlackMessage(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    channel: str
    user: str
    text: str
    ts: str
    thread_ts: str = ""


class SlackEvent(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    event_id: str
    team_id: str
    event: SlackMessage


class SlackSocketOpen(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    ok: bool
    url: str


class SlackSocketPayload(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    event_id: str
    team_id: str
    event: SlackMessage


class SlackSocketEnvelope(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    envelope_id: str
    payload: SlackSocketPayload


class SlackApiResponse(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    ok: bool
    error: str = ""


class SlackChannel:
    def __init__(
        self,
        api_url: str,
        token: str,
        signing_secret: str,
        channel_repositories: Mapping[str, str],
        submit: Callable[[WorkRequest], Job | None],
    ) -> None:
        self.source = WorkSource.SLACK
        self.adapter_id = "slack"
        self.api_url = api_url.rstrip("/")
        self.token = token
        self.signing_secret = signing_secret
        self.channel_repositories = channel_repositories
        self.submit = submit

    def receive(self, timestamp: str, signature: str, body: bytes) -> WorkRequest:
        if abs(time.time() - float(timestamp)) > 300:
            raise ValueError("stale Slack request")
        digest = hmac.new(
            self.signing_secret.encode(), b"v0:" + timestamp.encode() + b":" + body, hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(signature, f"v0={digest}"):
            raise ValueError("invalid Slack signature")
        payload = SlackEvent.model_validate_json(body)
        message = payload.event
        repository = self.channel_repositories.get(message.channel)
        if repository is None:
            raise ValueError("Slack channel is not mapped to a repository")
        return WorkRequest(
            idempotency_key=f"slack:{payload.team_id}:{payload.event_id}",
            conversation_id=f"{message.channel}:{message.thread_ts or message.ts}",
            actor=message.user,
            repository=repository,
            text=message.text,
            source=WorkSource.SLACK,
            delivery_adapter=self.adapter_id,
            delivery_target=f"{message.channel}:{message.thread_ts or message.ts}",
            source_metadata={"channel": message.channel, "timestamp": message.ts},
        )

    def submit_signed(self, timestamp: str, signature: str, body: bytes) -> WorkRequest:
        request = self.receive(timestamp, signature, body)
        self.submit(request)
        return request

    async def run(self) -> None:
        await asyncio.Event().wait()

    def accepts(self, delivery_target: str) -> bool:
        parts = delivery_target.split(":", maxsplit=1)
        return len(parts) == 2 and parts[0] in self.channel_repositories

    async def publish(self, update: WorkUpdate, delivery_key: str, delivery_target: str) -> None:
        if not self.accepts(delivery_target):
            raise ValueError(f"Slack channel cannot publish target: {delivery_target}")
        channel, timestamp = delivery_target.split(":", maxsplit=1)
        headers = {"Authorization": f"Bearer {self.token}"}
        payload = {
            "channel": channel,
            "thread_ts": timestamp,
            "text": update.message,
            "client_msg_id": delivery_key,
        }
        async with (
            aiohttp.ClientSession(headers=headers) as client,
            client.post(f"{self.api_url}/chat.postMessage", json=payload) as response,
        ):
            response.raise_for_status()
            result = SlackApiResponse.model_validate(await response.json())
            if not result.ok:
                raise RuntimeError(f"Slack rejected update: {result.error or 'unknown error'}")


class SlackSocketChannel(SlackChannel):
    def __init__(
        self,
        api_url: str,
        socket_url: str,
        token: str,
        channel_repositories: Mapping[str, str],
        submit: Callable[[WorkRequest], Job | None],
    ) -> None:
        super().__init__(api_url, token, "", channel_repositories, submit)
        self.socket_url = socket_url

    async def run(self) -> None:
        headers = {"Authorization": f"Bearer {self.token}"}
        while True:
            async with aiohttp.ClientSession(headers=headers) as client:
                async with client.post(self.socket_url) as response:
                    response.raise_for_status()
                    opened = SlackSocketOpen.model_validate(await response.json())
                if not opened.ok:
                    raise RuntimeError("Slack rejected Socket Mode connection")
                async with client.ws_connect(opened.url) as socket:
                    async for message in socket:
                        if message.type != aiohttp.WSMsgType.TEXT:
                            continue
                        envelope = SlackSocketEnvelope.model_validate_json(message.data)
                        payload = envelope.payload
                        slack_message = payload.event
                        repository = self.channel_repositories.get(slack_message.channel)
                        if repository is None:
                            raise ValueError("Slack channel is not mapped to a repository")
                        request = WorkRequest(
                            idempotency_key=f"slack:{payload.team_id}:{payload.event_id}",
                            conversation_id=(f"{slack_message.channel}:{slack_message.thread_ts or slack_message.ts}"),
                            actor=slack_message.user,
                            repository=repository,
                            text=slack_message.text,
                            source=WorkSource.SLACK,
                            delivery_adapter=self.adapter_id,
                            delivery_target=(f"{slack_message.channel}:{slack_message.thread_ts or slack_message.ts}"),
                            source_metadata={"channel": slack_message.channel, "timestamp": slack_message.ts},
                        )
                        self.submit(request)
                        await socket.send_json({"envelope_id": envelope.envelope_id})
