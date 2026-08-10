import signal
import subprocess
import sys
import time
from pathlib import Path


def test_generic_daemon_sigterm_runs_fastapi_lifespan_shutdown(tmp_path: Path) -> None:
    # GIVEN
    lifecycle = tmp_path / "lifespan.txt"
    program = """
import asyncio
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from ocint.daemon.run import serve_bounded

path = Path(sys.argv[1])

@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    path.write_text("started")
    try:
        yield
    finally:
        path.write_text("stopped")

asyncio.run(serve_bounded(FastAPI(lifespan=lifespan), "127.0.0.1", 0, asyncio.Event()))
"""
    process = subprocess.Popen((sys.executable, "-c", program, str(lifecycle)))

    try:
        deadline = time.monotonic() + 5
        while (not lifecycle.exists() or lifecycle.read_text() != "started") and time.monotonic() < deadline:
            if process.poll() is not None:
                raise AssertionError(f"generic daemon exited before startup with status {process.returncode}")
            time.sleep(0.01)
        assert lifecycle.read_text() == "started"

        # WHEN
        process.send_signal(signal.SIGTERM)
        return_code = process.wait(timeout=5)

        # THEN
        assert return_code == -signal.SIGTERM
        assert lifecycle.read_text() == "stopped"
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)
