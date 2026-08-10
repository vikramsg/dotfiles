"""Provider-neutral coordinator contracts and construction operations."""

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from ocint.daemon.coordinator.config import CoordinatorWorkspaceConfig, RepositoryCatalogueEntry
from ocint.daemon.coordinator.contracts import (
    CoordinatorDelivery,
    CoordinatorOperations,
    CoordinatorPersistence,
    CoordinatorWorker,
    OpenCodeCoordinator,
    RetryableCoordinatorDeliveryError,
    RetryableCoordinatorError,
    TerminalCoordinatorDeliveryError,
    TerminalCoordinatorError,
)
from ocint.daemon.coordinator.models import (
    ActorKind,
    ConversationIdentity,
    ConversationMessage,
    DeliveryLookup,
    DeliveryMissing,
    DeliveryReceipt,
    DeliveryRequest,
    IngestResult,
    MessageKind,
)
from ocint.daemon.coordinator.service import AuthorizationPolicy, ChannelAccess
from ocint.daemon.opencode import OpenCodeGateway


def create_configured_authorization_policy(channels: tuple[ChannelAccess, ...]) -> AuthorizationPolicy:
    from ocint.daemon.coordinator.service import ConfiguredAuthorizationPolicy

    return ConfiguredAuthorizationPolicy(channels)


def create_coordinator_operations(
    authorization: AuthorizationPolicy,
    response_chunk_characters: int,
    safe_failure_text: str,
) -> CoordinatorOperations:
    from ocint.daemon.coordinator.service import CoordinatorService

    return CoordinatorService(authorization, response_chunk_characters, safe_failure_text)


@contextmanager
def open_coordinator_persistence(database_path: Path) -> Iterator[CoordinatorPersistence]:
    from ocint.daemon.coordinator.repository import CoordinatorRepository
    from ocint.daemon.db import create_daemon_engine

    engine = create_daemon_engine(database_path)
    try:
        yield CoordinatorRepository(engine)
    finally:
        engine.dispose()


def create_opencode_coordinator(gateway: OpenCodeGateway, workspace: Path) -> OpenCodeCoordinator:
    from ocint.daemon.coordinator.opencode import OpenCodeCoordinatorAdapter

    return OpenCodeCoordinatorAdapter(gateway, workspace)


def create_coordinator_worker(
    repository: CoordinatorPersistence,
    service: CoordinatorOperations,
    opencode: OpenCodeCoordinator,
    delivery: CoordinatorDelivery,
    workspace: Path,
    retry_seconds: float,
    max_turn_retries: int,
    orphan_retention_seconds: float,
    delivery_interval_seconds: float,
) -> CoordinatorWorker:
    from ocint.daemon.coordinator.run import CoordinatorRuntime

    return CoordinatorRuntime(
        repository,
        service,
        opencode,
        delivery,
        workspace,
        retry_seconds,
        max_turn_retries,
        orphan_retention_seconds,
        delivery_interval_seconds,
    )


def generate_coordinator_workspace(config: CoordinatorWorkspaceConfig) -> None:
    from ocint.daemon.coordinator.workspace import CoordinatorWorkspace

    CoordinatorWorkspace(config).generate()


__all__ = [
    "ActorKind",
    "AuthorizationPolicy",
    "ChannelAccess",
    "ConversationIdentity",
    "ConversationMessage",
    "CoordinatorDelivery",
    "CoordinatorOperations",
    "CoordinatorPersistence",
    "CoordinatorWorker",
    "CoordinatorWorkspaceConfig",
    "DeliveryLookup",
    "DeliveryMissing",
    "DeliveryReceipt",
    "DeliveryRequest",
    "IngestResult",
    "MessageKind",
    "OpenCodeCoordinator",
    "RepositoryCatalogueEntry",
    "RetryableCoordinatorDeliveryError",
    "RetryableCoordinatorError",
    "TerminalCoordinatorDeliveryError",
    "TerminalCoordinatorError",
    "create_configured_authorization_policy",
    "create_coordinator_operations",
    "create_coordinator_worker",
    "create_opencode_coordinator",
    "generate_coordinator_workspace",
    "open_coordinator_persistence",
]
