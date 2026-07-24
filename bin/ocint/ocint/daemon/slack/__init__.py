"""Slack private-channel source facade."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Protocol

from ocint.daemon.models import ObservedMessage, ReplyRequest, ThreadObservations
from ocint.daemon.slack.config import SlackChannelConfig, SlackConfig
from ocint.daemon.slack.models import SlackAuth


class SlackGateway(Protocol):
    @property
    def source_prefix(self) -> str: ...
    async def observe(self) -> ThreadObservations: ...
    async def reply(self, request: ReplyRequest) -> ObservedMessage: ...


async def check_slack_access(config: SlackConfig, token: str) -> str:
    from ocint.daemon.slack.client import SlackClient

    client = SlackClient(token)
    await client.start()
    try:
        auth = await client.auth_test()
        if auth.team_id != config.workspace_id:
            raise ValueError(f"Slack token workspace {auth.team_id} does not match configured {config.workspace_id}")
        missing_scopes = config.required_scopes - client.granted_scopes
        if missing_scopes:
            raise ValueError(f"Slack token is missing required scopes: {', '.join(sorted(missing_scopes))}")
        for channel in config.channels:
            await client.history(channel.channel_id, channel.initial_oldest, limit=1)
        return f"workspace={auth.team_id}; channels={len(config.channels)}; scopes={','.join(sorted(config.required_scopes))}"
    finally:
        await client.close()


async def authenticate_slack_token(token: str) -> SlackAuth:
    from ocint.daemon.slack.client import SlackClient

    client = SlackClient(token)
    await client.start()
    try:
        return await client.auth_test()
    finally:
        await client.close()


async def validate_configured_slack_token(config: SlackConfig, token: str) -> SlackAuth:
    from ocint.daemon.slack.client import SlackClient

    client = SlackClient(token)
    await client.start()
    try:
        auth = await client.auth_test()
        if auth.team_id != config.workspace_id:
            raise ValueError(f"Slack token workspace {auth.team_id} does not match configured {config.workspace_id}")
        missing_scopes = config.required_scopes - client.granted_scopes
        if missing_scopes:
            raise ValueError(f"Slack token is missing required scopes: {', '.join(sorted(missing_scopes))}")
        return auth
    finally:
        await client.close()


@asynccontextmanager
async def open_slack_service(config: SlackConfig, token: str, database_path: Path) -> AsyncIterator[SlackGateway]:
    from ocint.daemon.db import create_daemon_engine
    from ocint.daemon.slack.client import SlackClient
    from ocint.daemon.slack.repository import SlackRepository
    from ocint.daemon.slack.service import SlackContext, SlackService

    engine = create_daemon_engine(database_path)
    client = SlackClient(token)
    await client.start()
    try:
        auth = await client.auth_test()
        if auth.team_id != config.workspace_id:
            raise ValueError(f"Slack token workspace {auth.team_id} does not match configured {config.workspace_id}")
        missing_scopes = config.required_scopes - client.granted_scopes
        if missing_scopes:
            raise ValueError(f"Slack token is missing required scopes: {', '.join(sorted(missing_scopes))}")
        yield SlackService(
            context=SlackContext(config=config, auth=auth, client=client, repository=SlackRepository(engine))
        )
    finally:
        await client.close()
        engine.dispose()


__all__ = [
    "SlackAuth",
    "SlackChannelConfig",
    "SlackConfig",
    "SlackGateway",
    "authenticate_slack_token",
    "check_slack_access",
    "open_slack_service",
    "validate_configured_slack_token",
]
