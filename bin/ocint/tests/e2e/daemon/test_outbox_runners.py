import asyncio
import socket
from pathlib import Path

import pytest
from aiohttp import web
from ocint.daemon.channels import SlackChannel
from ocint.daemon.config import (
    DaemonConfig,
    DaemonSettings,
    LoadedDaemonConfig,
    ProviderConfig,
    RepositoryConfig,
    SchedulerConfig,
)
from ocint.daemon.db import create_daemon_engine, migrate_daemon_db
from ocint.daemon.git import GitHubPublisher, ManagedCommand, RepositoryManager
from ocint.daemon.models import JobState, WorkRequest, WorkSource
from ocint.daemon.outbox_repository import OutboxRepository
from ocint.daemon.repository import ControlRepository
from ocint.daemon.run import ActiveConfig, DaemonRunner
from ocint.daemon.runner_repository import RunnerRepository
from ocint.daemon.runtime import OpenCodeRuntime
from ocint.daemon.service import cancel_job, terminal_update
from ocint.daemon.workspace_repository import WorkspaceRepository
from pydantic import BaseModel, ConfigDict, HttpUrl


class DeliveryObservation(BaseModel):
    model_config = ConfigDict(frozen=True)

    delivery_id: str
    target: str
    message: str


@pytest.mark.asyncio
async def test_two_live_runners_renew_slow_exact_target_terminal_deliveries(tmp_path: Path) -> None:
    # GIVEN completed, failed, and cancelled jobs plus a provider slower than the outbox lease
    deliveries: list[DeliveryObservation] = []

    async def slack_post(request: web.Request) -> web.Response:
        payload = await request.json()
        deliveries.append(
            DeliveryObservation(
                delivery_id=payload["client_msg_id"],
                target=f"{payload['channel']}:{payload['thread_ts']}",
                message=payload["text"],
            )
        )
        await asyncio.sleep(2)
        return web.json_response({"ok": True, "ts": "1.2"})

    provider = web.Application()
    provider.add_routes([web.post("/chat.postMessage", slack_post)])
    provider_runner = web.AppRunner(provider)
    await provider_runner.setup()
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    await web.SockSite(provider_runner, listener).start()
    provider_url = f"http://127.0.0.1:{listener.getsockname()[1]}"
    path = tmp_path / "control.sqlite"
    migrate_daemon_db(path)
    engine = create_daemon_engine(path)
    repository = ControlRepository(engine)
    config = DaemonConfig(
        database_path=path,
        mirror_root=tmp_path / "mirrors",
        worktree_root=tmp_path / "worktrees",
        repositories=[RepositoryConfig(name="repo", remote_url="file:///remote")],
        scheduler=SchedulerConfig(
            capacity=1,
            lease_seconds=10,
            heartbeat_seconds=1,
            poll_seconds=0.05,
            outbox_lease_seconds=1,
        ),
        providers=ProviderConfig(
            github_api_url=HttpUrl(provider_url),
            slack_api_url=HttpUrl(provider_url),
            slack_socket_url=HttpUrl(provider_url),
        ),
    )
    settings = DaemonSettings(config=tmp_path / "daemon.toml")
    active = ActiveConfig(LoadedDaemonConfig(path=tmp_path / "daemon.toml", config=config, settings=settings), tmp_path)
    complete = repository.submit(
        WorkRequest(
            idempotency_key="complete",
            conversation_id="C1:complete",
            actor="actor",
            repository="repo",
            text="complete",
            source=WorkSource.SLACK,
            delivery_adapter="slack",
            delivery_target="C1:complete",
        )
    )
    complete_claim = repository.claim("seed", 1, 60, "{}")
    assert complete_claim is not None
    repository.finish_with_outbox(
        complete_claim,
        JobState.COMPLETED,
        "",
        terminal_update(complete, JobState.COMPLETED, "job completed"),
    )
    failed = repository.submit(
        WorkRequest(
            idempotency_key="failed",
            conversation_id="C1:failed",
            actor="actor",
            repository="repo",
            text="failed",
            source=WorkSource.SLACK,
            delivery_adapter="slack",
            delivery_target="C1:failed",
        )
    )
    failed_claim = repository.claim("seed", 1, 60, "{}")
    assert failed_claim is not None
    repository.finish_with_outbox(
        failed_claim,
        JobState.FAILED,
        "failed",
        terminal_update(failed, JobState.FAILED, "failed"),
    )
    cancelled = repository.submit(
        WorkRequest(
            idempotency_key="cancelled",
            conversation_id="C1:cancelled",
            actor="actor",
            repository="repo",
            text="cancelled",
            source=WorkSource.SLACK,
            delivery_adapter="slack",
            delivery_target="C1:cancelled",
        )
    )
    cancel_job(repository, cancelled.id)
    channel = SlackChannel(provider_url, "token", "secret", {"C1": "repo"}, repository.submit)
    manager = RepositoryManager(
        config.mirror_root,
        config.worktree_root,
        ManagedCommand(5, 4096, frozenset()),
        {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"},
        {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "HOME": str(tmp_path)},
    )
    runtime = OpenCodeRuntime("http://127.0.0.1:1", "", "", 1)
    runner_one = DaemonRunner(
        active,
        repository,
        manager,
        runtime,
        GitHubPublisher(provider_url, ""),
        [channel],
        OutboxRepository(engine),
        RunnerRepository(engine, repository),
        WorkspaceRepository(engine),
    )
    runner_two = DaemonRunner(
        active,
        repository,
        manager,
        runtime,
        GitHubPublisher(provider_url, ""),
        [channel],
        OutboxRepository(engine),
        RunnerRepository(engine, repository),
        WorkspaceRepository(engine),
    )

    # WHEN both daemon runners compete while each provider operation exceeds the original lease
    first_task = asyncio.create_task(runner_one.run())
    second_task = asyncio.create_task(runner_two.run())
    deadline = asyncio.get_running_loop().time() + 20
    while len(deliveries) < 6 and asyncio.get_running_loop().time() < deadline:
        await asyncio.sleep(0.1)

    # THEN each accepted/terminal exact-target delivery is attempted once despite two runners
    assert len(deliveries) == 6
    assert len({item.delivery_id for item in deliveries}) == 6
    assert channel.adapter_id == "slack"
    terminal = sorted(f"{item.target}|{item.message}" for item in deliveries if not item.message.endswith("accepted"))
    assert terminal == ["C1:cancelled|cancelled", "C1:complete|job completed", "C1:failed|failed"]
    runner_one.stopping.set()
    runner_two.stopping.set()
    await asyncio.gather(first_task, second_task)
    await provider_runner.cleanup()
    engine.dispose()
