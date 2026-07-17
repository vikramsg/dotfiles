import os
import subprocess
import sys
from pathlib import Path

import pytest
from ocint.daemon.config import RepositoryConfig
from ocint.daemon.git import GitManager


@pytest.mark.asyncio
async def test_real_repository_validation_commit_and_ssh_push(tmp_path: Path) -> None:
    # GIVEN
    remote = tmp_path / "remote.git"
    seed = tmp_path / "seed"
    subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True)
    subprocess.run(["git", "init", "-b", "main", str(seed)], check=True, capture_output=True)
    (seed / "README.md").write_text("seed\n")
    subprocess.run(["git", "-C", str(seed), "add", "README.md"], check=True)
    subprocess.run(
        ["git", "-C", str(seed), "-c", "user.name=Seed", "-c", "user.email=seed@example.test", "commit", "-m", "seed"],
        check=True,
        capture_output=True,
    )
    subprocess.run(["git", "-C", str(seed), "remote", "add", "origin", str(remote)], check=True)
    subprocess.run(["git", "-C", str(seed), "push", "origin", "main"], check=True, capture_output=True)
    transport = tmp_path / "bin"
    transport.mkdir()
    ssh = transport / "ssh"
    ssh.write_text('#!/bin/sh\nfor argument do command="$argument"; done\nexec sh -c "$command"\n')
    ssh.chmod(0o755)
    path = f"{transport}:{os.environ['PATH']}"
    manager = GitManager(
        tmp_path / "mirrors",
        tmp_path / "worktrees",
        {"PATH": path, "LANG": "C.UTF-8", "CI": "1"},
        {"PATH": path, "LANG": "C.UTF-8", "GIT_TERMINAL_PROMPT": "0", "SSH_AUTH_SOCK": "/tmp/test-agent"},
        30,
        65536,
    )
    repository = RepositoryConfig(
        name="repo",
        remote_url=f"ssh://example{remote}",
        github_repository="owner/repo",
        author_name="Daemon Agent",
        author_email="daemon@example.test",
    )

    # WHEN
    worktree = await manager.provision(repository, "job")
    (worktree.path / "result.txt").write_text("result\n")
    await manager.validate(worktree, [[sys.executable, "-c", "import os; assert 'SSH_AUTH_SOCK' not in os.environ"]])
    commit = await manager.commit(worktree, "result", repository.author_name, repository.author_email)
    await manager.push(worktree)
    author = subprocess.run(
        ["git", "-C", str(worktree.path), "show", "-s", "--format=%an <%ae>", commit],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    branch = subprocess.run(
        ["git", "--git-dir", str(remote), "rev-parse", "refs/heads/ocint/job"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    # THEN
    assert author == "Daemon Agent <daemon@example.test>"
    assert branch == commit
