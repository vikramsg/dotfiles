import os
import subprocess
import sys
from pathlib import Path

from ocint.ctx.refresh.jsonlog import append_refresh_event


def schedule_refresh_worker(*, ctx_db_path: Path, source_db_path: Path, log_path: Path) -> int:
    """Launch the hidden refresh worker detached from the foreground search process."""
    log_path.parent.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["OCINT_CTX_DB"] = str(ctx_db_path)
    env["OPENCODE_DB"] = str(source_db_path)
    env["OCINT_CTX_REFRESH_LOG_JSONL"] = "1"
    command = [sys.executable, "-c", "from ocint.cli import main; main()", "ctx", "refresh-worker"]
    append_refresh_event(
        log_path,
        "refresh_worker_scheduled",
        ctx_db=ctx_db_path,
        source_db=source_db_path,
        command=command,
    )
    with log_path.open("ab") as log_file:
        process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            env=env,
            start_new_session=True,
        )
    pid = int(process.pid)
    append_refresh_event(
        log_path,
        "refresh_worker_spawned",
        pid=pid,
        ctx_db=ctx_db_path,
        source_db=source_db_path,
    )
    return pid
