import asyncio
from typing import Protocol

import uvicorn
from fastapi import FastAPI


class IdleExecutor(Protocol):
    activity_generation: int

    @property
    def is_idle(self) -> bool: ...

    async def wait_until_idle(self) -> None: ...


async def wait_for_idle(executor: IdleExecutor, idle_seconds: int, shutdown_event: asyncio.Event) -> None:
    while True:
        await executor.wait_until_idle()
        observed_generation = executor.activity_generation
        await asyncio.sleep(idle_seconds)
        if executor.is_idle and executor.activity_generation == observed_generation:
            shutdown_event.set()
            return


async def serve_bounded(app: FastAPI, host: str, port: int, shutdown_event: asyncio.Event) -> None:
    server = uvicorn.Server(uvicorn.Config(app, host=host, port=port, log_config=None, access_log=False))
    serving = asyncio.create_task(server.serve())
    waiting = asyncio.create_task(shutdown_event.wait())
    done, _pending = await asyncio.wait((serving, waiting), return_when=asyncio.FIRST_COMPLETED)
    if waiting in done:
        server.should_exit = True
    await serving
    waiting.cancel()
    await asyncio.gather(waiting, return_exceptions=True)
