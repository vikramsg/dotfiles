import asyncio
from dataclasses import dataclass

import pytest
from ocint.daemon.run import wait_for_idle


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


@pytest.mark.asyncio
async def test_idle_shutdown_requires_unchanged_generation() -> None:
    # GIVEN
    executor = FakeExecutor()
    shutdown = asyncio.Event()

    # WHEN
    task = asyncio.create_task(wait_for_idle(executor, 1, shutdown))
    await asyncio.sleep(0.1)
    executor.activity_generation += 1
    await asyncio.sleep(1)

    # THEN
    assert not shutdown.is_set()
    await asyncio.wait_for(task, 1.2)
    assert shutdown.is_set()
