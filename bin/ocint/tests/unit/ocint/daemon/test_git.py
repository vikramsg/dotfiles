import subprocess
import threading
from pathlib import Path

import pytest
from ocint.daemon.config import RepositoryConfig
from ocint.daemon.git import ManagedCommand, RepositoryManager


def test_managed_command_redacts_secrets_and_limits_repository_environment(tmp_path: Path) -> None:
    # GIVEN a managed command with one publication secret and an explicit validation environment
    command = ManagedCommand(timeout_seconds=5, output_bytes=1024, secrets=frozenset(["publisher-secret"]))

    # WHEN repository-controlled validation prints the secret and fails
    with pytest.raises(RuntimeError) as failure:
        command.run(
            ["python3", "-c", "import os,sys; print('publisher-secret', os.getenv('LEAK','missing')); sys.exit(1)"],
            tmp_path,
            {"PATH": "/usr/local/bin:/usr/bin:/bin", "LANG": "C.UTF-8"},
            threading.Event(),
        )

    # THEN diagnostics are redacted and no ambient environment was added
    assert "publisher-secret" not in str(failure.value)
    assert "[REDACTED]" in str(failure.value)


def test_managed_command_cancels_the_process_group(tmp_path: Path) -> None:
    # GIVEN a long-running managed subprocess and a cancellation fence
    cancelled = threading.Event()
    threading.Timer(0.1, cancelled.set).start()
    command = ManagedCommand(timeout_seconds=10, output_bytes=1024, secrets=frozenset())

    # WHEN lease loss signals cancellation
    with pytest.raises(RuntimeError, match="cancelled"):
        command.run(
            ["python3", "-c", "import time; time.sleep(30)"],
            tmp_path,
            {"PATH": "/usr/local/bin:/usr/bin:/bin", "LANG": "C.UTF-8"},
            cancelled,
        )

    # THEN the command returns after terminating its process group
    assert cancelled.is_set()


def test_repository_retirement_retries_after_effect_before_checkpoint(tmp_path: Path) -> None:
    # GIVEN a managed worktree whose first external removal succeeds before durable checkpoint
    source = tmp_path / "source"
    remote = tmp_path / "remote.git"
    source.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=source, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Daemon Test"], cwd=source, check=True)
    subprocess.run(["git", "config", "user.email", "daemon@example.test"], cwd=source, check=True)
    (source / "README.md").write_text("seed\n")
    subprocess.run(["git", "add", "README.md"], cwd=source, check=True)
    subprocess.run(["git", "commit", "-m", "seed"], cwd=source, check=True, capture_output=True)
    subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True)
    subprocess.run(["git", "remote", "add", "origin", str(remote)], cwd=source, check=True)
    subprocess.run(["git", "push", "origin", "main"], cwd=source, check=True, capture_output=True)
    environment = {"PATH": "/usr/local/bin:/usr/bin:/bin", "LANG": "C.UTF-8", "HOME": str(tmp_path)}
    manager = RepositoryManager(
        tmp_path / "mirrors",
        tmp_path / "worktrees",
        ManagedCommand(10, 8192, frozenset()),
        environment,
        environment,
    )
    repository = RepositoryConfig(name="repo", remote_url=str(remote))
    cancelled = threading.Event()
    worktree = manager.provision(repository, "job", cancelled)
    manager.retire(repository, worktree, cancelled)

    # WHEN a new owner retries the same removal after the missing checkpoint
    manager.retire(repository, worktree, cancelled)

    # THEN absent worktree and Git metadata are treated as successful idempotent cleanup
    assert worktree.path.exists() is False
