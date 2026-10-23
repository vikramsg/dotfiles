import asyncio
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Protocol

import uvicorn
from fastapi import FastAPI

from ocint.daemon.logging import get_logger

logger = get_logger("run")


class IdleExecutor(Protocol):
    activity_generation: int

    @property
    def is_idle(self) -> bool: ...

    async def wait_until_idle(self) -> None: ...
    async def wait_for_completion(self) -> None: ...


class IdleTasks(Protocol):
    async def reconcile(self) -> bool: ...


class SignalFreeUvicornServer(uvicorn.Server):
    @contextmanager
    def capture_signals(self) -> Iterator[None]:
        yield


async def wait_for_idle(
    executor: IdleExecutor, idle_seconds: int, shutdown_event: asyncio.Event, tasks: IdleTasks
) -> None:
    while True:
        if not executor.is_idle:
            await executor.wait_for_completion()
            await tasks.reconcile()
            continue
        if await tasks.reconcile():
            await asyncio.sleep(0)
            continue
        if not executor.is_idle:
            continue
        observed_generation = executor.activity_generation
        logger.info("idle grace started", seconds=idle_seconds, activity_generation=observed_generation)
        await asyncio.sleep(idle_seconds)
        unresolved = await tasks.reconcile()
        if not unresolved and executor.is_idle and executor.activity_generation == observed_generation:
            logger.info("idle grace completed", seconds=idle_seconds)
            shutdown_event.set()
            return
        logger.info("idle grace reset", activity_generation=executor.activity_generation)


async def serve_bounded(app: FastAPI, host: str, port: int, shutdown_event: asyncio.Event) -> None:
    server = uvicorn.Server(uvicorn.Config(app, host=host, port=port, log_config=None, access_log=False))
    await _serve_bounded(server, host, port, shutdown_event)


async def serve_signal_free_ingress(app: FastAPI, host: str, port: int, shutdown_event: asyncio.Event) -> None:
    server = SignalFreeUvicornServer(uvicorn.Config(app, host=host, port=port, log_config=None, access_log=False))
    await _serve_bounded(server, host, port, shutdown_event)


async def _serve_bounded(server: uvicorn.Server, host: str, port: int, shutdown_event: asyncio.Event) -> None:
    logger.info("API server starting", host=host, port=port)
    serving = asyncio.create_task(server.serve())
    waiting = asyncio.create_task(shutdown_event.wait())
    done, _pending = await asyncio.wait((serving, waiting), return_when=asyncio.FIRST_COMPLETED)
    if waiting in done:
        server.should_exit = True
    await serving
    logger.info("API server stopped", host=host, port=port)
    waiting.cancel()
    await asyncio.gather(waiting, return_exceptions=True)
