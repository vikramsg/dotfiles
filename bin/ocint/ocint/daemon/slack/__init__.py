"""Slack Events API and delivery facade."""

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Protocol

from fastapi import FastAPI

from ocint.daemon.coordinator import (
    ActorKind,
    ConversationMessage,
    CoordinatorDelivery,
    DeliveryLookup,
    DeliveryReceipt,
    DeliveryRequest,
    IngestResult,
    MessageKind,
)
from ocint.daemon.slack.config import (
    CoordinatorSlackChannelConfig,
    CoordinatorSlackConfig,
    SlackEventsConfig,
)
from ocint.daemon.slack.models import SlackAuth, SlackEventCallback, SlackEventPayload


class SlackActorPolicy(Protocol):
    def classify(self, callback: SlackEventCallback) -> ActorKind: ...


class SlackCoordinatorDeliveryGateway(CoordinatorDelivery, Protocol):
    async def find_delivery(self, request: DeliveryRequest) -> DeliveryLookup: ...
    async def post(self, request: DeliveryRequest) -> DeliveryReceipt: ...


def create_slack_events_app[Prepared](
    config: SlackEventsConfig,
    workspace_id: str,
    signing_secret: str,
    prepare: Callable[[ConversationMessage, MessageKind, ActorKind], Prepared],
    ingest: Callable[[Prepared], IngestResult],
    actor_classifier: SlackActorPolicy,
    wake: Callable[[], None],
) -> FastAPI:
    from ocint.daemon.slack.events import create_slack_events_app as create_app

    return create_app(
        config,
        workspace_id,
        signing_secret,
        prepare,
        ingest,
        actor_classifier,
        wake,
        processing_timeout_seconds=config.processing_timeout_seconds,
    )


def production_slack_actor_policy() -> SlackActorPolicy:
    from ocint.daemon.slack.service import ProductionSlackActorClassifier

    return ProductionSlackActorClassifier()


@asynccontextmanager
async def open_slack_coordinator_delivery(token: str) -> AsyncIterator[SlackCoordinatorDeliveryGateway]:
    from ocint.daemon.slack.client import SlackClient
    from ocint.daemon.slack.service import SlackCoordinatorDelivery

    client = SlackClient(token)
    await client.start()
    try:
        yield SlackCoordinatorDelivery(client)
    finally:
        await client.close()


async def check_slack_access(config: CoordinatorSlackConfig, token: str) -> str:
    auth = await validate_coordinator_slack_access(config, token)
    return (
        f"workspace={auth.team_id}; channels={len(config.channels)}; scopes={','.join(sorted(config.required_scopes))}"
    )


async def validate_coordinator_slack_access(config: CoordinatorSlackConfig, token: str) -> SlackAuth:
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
            await client.history(channel.channel_id, limit=1)
        return auth
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


async def validate_configured_slack_token(config: CoordinatorSlackConfig, token: str) -> SlackAuth:
    return await validate_coordinator_slack_access(config, token)


__all__ = [
    "CoordinatorSlackChannelConfig",
    "CoordinatorSlackConfig",
    "SlackActorPolicy",
    "SlackAuth",
    "SlackCoordinatorDeliveryGateway",
    "SlackEventPayload",
    "SlackEventsConfig",
    "authenticate_slack_token",
    "check_slack_access",
    "create_slack_events_app",
    "open_slack_coordinator_delivery",
    "production_slack_actor_policy",
    "validate_configured_slack_token",
    "validate_coordinator_slack_access",
]
