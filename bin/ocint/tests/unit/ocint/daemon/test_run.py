import asyncio
import signal
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

import pytest
import uvicorn
from fastapi import FastAPI
from ocint.daemon.run import SignalFreeUvicornServer, serve_signal_free_ingress, wait_for_idle


@dataclass
class FakeExecutor:
    activity_generation: int = 0
    idle: bool = True

    @property
    def is_idle(self) -> bool:
        return self.idle

    async def wait_until_idle(self) -> None:
        while not self.idle:
            await asyncio.sleep(0)

    async def wait_for_completion(self) -> None:
        while not self.idle:
            await asyncio.sleep(0)


@dataclass
class FakeTasks:
    unresolved: bool = False

    async def reconcile(self) -> bool:
        return self.unresolved


@pytest.mark.asyncio
async def test_idle_shutdown_requires_unchanged_generation() -> None:
    # GIVEN
    executor = FakeExecutor()
    shutdown = asyncio.Event()

    # WHEN
    task = asyncio.create_task(wait_for_idle(executor, 1, shutdown, FakeTasks()))
    await asyncio.sleep(0.1)
    executor.activity_generation += 1
    await asyncio.sleep(1)

    # THEN
    assert not shutdown.is_set()
    await asyncio.wait_for(task, 1.2)
    assert shutdown.is_set()


@pytest.mark.asyncio
async def test_idle_shutdown_waits_for_unresolved_tasks() -> None:
    # GIVEN
    executor = FakeExecutor()
    tasks = FakeTasks(unresolved=True)
    shutdown = asyncio.Event()

    # WHEN
    waiting = asyncio.create_task(wait_for_idle(executor, 1, shutdown, tasks))
    await asyncio.sleep(0.1)

    # THEN
    assert not shutdown.is_set()
    tasks.unresolved = False
    await asyncio.wait_for(waiting, 1.2)
    assert shutdown.is_set()


def test_signal_free_ingress_server_does_not_capture_process_signals() -> None:
    # GIVEN
    server = SignalFreeUvicornServer(uvicorn.Config(FastAPI()))
    handled = (signal.SIGTERM, signal.SIGINT)
    previous = tuple(signal.getsignal(process_signal) for process_signal in handled)

    # WHEN
    with server.capture_signals():
        captured = tuple(signal.getsignal(process_signal) for process_signal in handled)

    # THEN
    assert captured == previous


@pytest.mark.asyncio
async def test_signal_free_ingress_stops_from_injected_shutdown_event() -> None:
    # GIVEN
    started = asyncio.Event()
    lifecycle: list[str] = []

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        lifecycle.append("started")
        started.set()
        yield
        lifecycle.append("stopped")

    shutdown = asyncio.Event()
    serving = asyncio.create_task(serve_signal_free_ingress(FastAPI(lifespan=lifespan), "127.0.0.1", 0, shutdown))
    await asyncio.wait_for(started.wait(), 1)

    # WHEN
    shutdown.set()
    await asyncio.wait_for(serving, 1)

    # THEN
    assert lifecycle == ["started", "stopped"]
