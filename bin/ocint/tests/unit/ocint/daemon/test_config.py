from pathlib import Path

import pytest
from ocint.daemon.config import DaemonSettings, load_daemon_config


def test_config_resolves_explicit_path_and_validates_typed_values(tmp_path: Path) -> None:
    # GIVEN a complete daemon TOML file selected through typed settings
    config_path = tmp_path / "daemon.toml"
    config_path.write_text(
        f'database_path = "{tmp_path / "control.sqlite"}"\n'
        f'mirror_root = "{tmp_path / "mirrors"}"\n'
        f'worktree_root = "{tmp_path / "worktrees"}"\n'
        'repositories = [{ name = "repo", remote_url = "file:///remote" }]\n'
        "[scheduler]\ncapacity = 3\n"
    )
    settings = DaemonSettings(config=config_path)

    # WHEN configuration is loaded
    loaded = load_daemon_config(settings, tmp_path)

    # THEN paths and scheduler policy are concrete validated values
    assert loaded.path == config_path
    assert loaded.config.scheduler.capacity == 3
    assert loaded.config.repository("repo").default_branch == "main"


def test_config_uses_xdg_fallback(tmp_path: Path) -> None:
    # GIVEN no explicit daemon path and an XDG root
    settings = DaemonSettings(xdg_config_home=tmp_path)

    # WHEN its path is resolved
    path = settings.config_path(Path("/unused"))

    # THEN the documented XDG path is selected
    assert path == (tmp_path / "ocint" / "daemon.toml").resolve()


def test_scheduler_rejects_heartbeat_that_cannot_renew_before_expiry(tmp_path: Path) -> None:
    # GIVEN a configuration whose heartbeat is not shorter than its lease
    config_path = tmp_path / "daemon.toml"
    config_path.write_text(
        f'database_path = "{tmp_path / "control.sqlite"}"\n'
        f'mirror_root = "{tmp_path / "mirrors"}"\n'
        f'worktree_root = "{tmp_path / "worktrees"}"\n'
        'repositories = [{ name = "repo", remote_url = "file:///remote" }]\n'
        "[scheduler]\nlease_seconds = 10\nheartbeat_seconds = 10\n"
    )

    # WHEN typed configuration is loaded
    # THEN unsafe lease timing is rejected before daemon startup
    with pytest.raises(ValueError, match="heartbeat_seconds"):
        load_daemon_config(DaemonSettings(config=config_path), tmp_path)
