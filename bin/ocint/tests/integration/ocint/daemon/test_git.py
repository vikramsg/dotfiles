import asyncio
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from ocint.daemon.config import RepositoryConfig
from ocint.daemon.git import GitManager


@pytest.mark.asyncio
async def test_concurrent_cold_provisioning_serializes_mirror_and_preserves_least_privilege(tmp_path: Path) -> None:
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
    events = tmp_path / "git-events.jsonl"
    real_git = shutil.which("git")
    assert real_git is not None
    git = transport / "git"
    git.write_text(
        f"""#!{sys.executable}
import json, os, subprocess, sys
with open({str(events)!r}, "a") as stream:
    stream.write(json.dumps({{"arguments": sys.argv[1:], "ssh_auth_sock": os.environ.get("SSH_AUTH_SOCK")}}) + "\\n")
raise SystemExit(subprocess.run([{real_git!r}, *sys.argv[1:]]).returncode)
"""
    )
    git.chmod(0o755)
    ssh = transport / "ssh"
    ssh.write_text('#!/bin/sh\nfor argument do command="$argument"; done\nexec sh -c "$command"\n')
    ssh.chmod(0o755)
    path = f"{transport}:{os.environ['PATH']}"
    manager = GitManager(
        tmp_path / "mirrors",
        tmp_path / "worktrees",
        {"PATH": path, "LANG": "C.UTF-8", "CI": "1"},
        {"PATH": path, "LANG": "C.UTF-8", "GIT_TERMINAL_PROMPT": "0"},
        "/tmp/test-agent",
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
    worktree, second_worktree = await asyncio.gather(
        manager.provision(repository, "job"),
        manager.provision(repository, "job-two"),
    )
    (worktree.path / "result.txt").write_text("result\n")
    await manager.validate(worktree, ((sys.executable, "-c", "import os; assert 'SSH_AUTH_SOCK' not in os.environ"),))
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
    git_events = [json.loads(line) for line in events.read_text().splitlines()]
    second_revision = subprocess.run(
        ["git", "-C", str(second_worktree.path), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    # THEN
    assert author == "Daemon Agent <daemon@example.test>"
    assert branch == commit
    assert second_revision == worktree.base_revision
    assert sum(event["arguments"][0] == "clone" for event in git_events) == 1
    assert (tmp_path / "mirrors" / "repo.git").is_dir()
    assert worktree.path.is_dir()
    assert second_worktree.path.is_dir()
    assert git_events
    for event in git_events:
        command = event["arguments"][0]
        if command in {"clone", "fetch", "push"}:
            assert event["ssh_auth_sock"] == "/tmp/test-agent"
        else:
            assert event["ssh_auth_sock"] is None


@pytest.mark.asyncio
async def test_reprovision_preserves_uncheckpointed_worktree_after_remote_advances(tmp_path: Path) -> None:
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
        {"PATH": path, "LANG": "C.UTF-8", "GIT_TERMINAL_PROMPT": "0"},
        "/tmp/test-agent",
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
    original = await manager.provision(repository, "job")
    (seed / "README.md").write_text("advanced\n")
    subprocess.run(["git", "-C", str(seed), "add", "README.md"], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(seed),
            "-c",
            "user.name=Seed",
            "-c",
            "user.email=seed@example.test",
            "commit",
            "-m",
            "advance",
        ],
        check=True,
        capture_output=True,
    )
    subprocess.run(["git", "-C", str(seed), "push", "origin", "main"], check=True, capture_output=True)
    advanced_revision = subprocess.run(
        ["git", "--git-dir", str(remote), "rev-parse", "refs/heads/main"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    # WHEN
    recovered = await manager.provision(repository, "job")
    actual_revision = subprocess.run(
        ["git", "-C", str(recovered.path), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    # THEN
    assert advanced_revision != original.base_revision
    assert recovered.path == original.path
    assert recovered.branch == original.branch == "ocint/job"
    assert recovered.base_revision == actual_revision == original.base_revision
    with pytest.raises(ValueError, match="OpenCode produced no changes"):
        await manager.validate(recovered, ())
