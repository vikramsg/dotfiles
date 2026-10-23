"""Public GitHub facade and the only production construction boundary.

Configuration models and service contracts are safe to import without loading
runtime implementations. Production modules import GitHub APIs only from this
package facade.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Protocol

from ocint.daemon.github.config import GitHubConfig
from ocint.daemon.github.models import GitHubRepositoryPolicies, GitHubRepositoryPolicy
from ocint.daemon.models import (
    ObservedMessage,
    PublicationRequest,
    PublicationResult,
    ReplyRequest,
    ThreadObservations,
)


class GitHubGateway(Protocol):
    @property
    def source_prefix(self) -> str: ...
    async def observe(self) -> ThreadObservations: ...
    async def reply(self, request: ReplyRequest) -> ObservedMessage: ...
    async def publish(self, request: PublicationRequest) -> PublicationResult: ...


@asynccontextmanager
async def open_github_service(
    config: GitHubConfig,
    repositories: GitHubRepositoryPolicies,
    token: str,
    database_path: Path,
) -> AsyncIterator[GitHubGateway]:
    """Construct and manage the concrete GitHub service.

    This factory exists because GitHub configuration is feature-owned and
    imported through this lightweight facade, while production callers may not
    import concrete GitHub implementation modules. Concrete imports remain local
    so configuration imports do not initialize HTTP, persistence, or service
    implementations.

    The daemon CLI enters this context at its outermost lifecycle boundary. The
    factory constructs and owns the GitHub client and persistence engine, starts
    the HTTP client, yields one service instance for injection through the
    consumer-owned protocols, and closes resources in reverse order.
    """
    from ocint.daemon.db import create_daemon_engine
    from ocint.daemon.github.client import GitHubClient
    from ocint.daemon.github.repository import GitHubRepository
    from ocint.daemon.github.service import GitHubContext, GitHubService

    engine = create_daemon_engine(database_path)
    client = GitHubClient(str(config.api_url), token)
    await client.start()
    try:
        yield GitHubService(
            context=GitHubContext(
                config=config,
                repositories=repositories,
                client=client,
                repository=GitHubRepository(engine),
            )
        )
    finally:
        await client.close()
        engine.dispose()


__all__ = [
    "GitHubConfig",
    "GitHubGateway",
    "GitHubRepositoryPolicies",
    "GitHubRepositoryPolicy",
    "open_github_service",
]
