from pathlib import Path

import pytest
from ocint.daemon.config import DaemonSettings, load_daemon_config
from ocint.daemon.run import ActiveConfig


def test_reload_atomically_applies_scheduler_policy_and_rejects_runtime_wiring(tmp_path: Path) -> None:
    # GIVEN a loaded daemon configuration
    path = tmp_path / "daemon.toml"
    path.write_text(
        f'database_path = "{tmp_path / "control.sqlite"}"\n'
        f'mirror_root = "{tmp_path / "mirrors"}"\n'
        f'worktree_root = "{tmp_path / "worktrees"}"\n'
        'repositories = [{ name = "repo", remote_url = "file:///remote" }]\n'
        "[scheduler]\ncapacity = 1\nlease_seconds = 10\nheartbeat_seconds = 1\n"
        "[api]\nport = 8732\n"
    )
    settings = DaemonSettings(config=path)
    active = ActiveConfig(load_daemon_config(settings, tmp_path), tmp_path)

    # WHEN a reload changes only live scheduler capacity
    path.write_text(
        f'database_path = "{tmp_path / "control.sqlite"}"\n'
        f'mirror_root = "{tmp_path / "mirrors"}"\n'
        f'worktree_root = "{tmp_path / "worktrees"}"\n'
        'repositories = [{ name = "repo", remote_url = "file:///remote" }]\n'
        "[scheduler]\ncapacity = 2\nlease_seconds = 10\nheartbeat_seconds = 1\n"
        "[api]\nport = 8732\n"
    )
    active.reload()

    # THEN it activates atomically
    assert active.loaded.config.scheduler.capacity == 2

    # WHEN runtime API wiring changes
    path.write_text(
        f'database_path = "{tmp_path / "control.sqlite"}"\n'
        f'mirror_root = "{tmp_path / "mirrors"}"\n'
        f'worktree_root = "{tmp_path / "worktrees"}"\n'
        'repositories = [{ name = "repo", remote_url = "file:///remote" }]\n'
        "[scheduler]\ncapacity = 3\nlease_seconds = 10\nheartbeat_seconds = 1\n"
        "[api]\nport = 9999\n"
    )

    # THEN the named non-reloadable field is rejected and the active snapshot is unchanged
    with pytest.raises(ValueError, match="api"):
        active.reload()
    assert active.loaded.config.scheduler.capacity == 2
    assert active.loaded.config.api.port == 8732
