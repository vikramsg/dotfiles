import re
from io import StringIO
from pathlib import Path

from ocint.daemon.config import CoordinatorConfig, DaemonConfig, GitHubConfig, RepositoryConfig
from ocint.daemon.git import GitConfig
from ocint.daemon.lch.render import render_status
from ocint.daemon.lch.systemd import LifecycleStatus
from ocint.daemon.models import GitHubLogin
from ocint.daemon.opencode import OpenCodeConfig
from ocint.daemon.slack import CoordinatorSlackChannelConfig, CoordinatorSlackConfig, SlackEventsConfig
from pydantic import HttpUrl
from rich.console import Console


def test_status_rendering_has_colored_sections_and_copyable_log_commands(tmp_path: Path) -> None:
    # GIVEN
    status = LifecycleStatus(
        installed=True,
        timer_state="active",
        timer_substate="waiting",
        last_trigger="2026-07-18 06:26:10 UTC",
        next_trigger="2026-07-18 06:42:44 UTC",
        service_state="inactive",
        service_substate="dead",
        last_result="success",
        last_exit_status="0",
        last_started="2026-07-18 06:26:10 UTC",
        last_completed="2026-07-18 06:27:44 UTC",
        coordinator_state="active",
        coordinator_substate="running",
        coordinator_unit_state="enabled",
        ngrok_state="inactive",
        ngrok_substate="dead",
        ngrok_unit_state="disabled",
        log_path=tmp_path / "home" / ".local" / "state" / "ocint" / "daemon.log",
        home=tmp_path / "home",
    )
    config = DaemonConfig(
        database_path=tmp_path / "daemon.sqlite",
        mirror_root=tmp_path / "mirrors",
        worktree_root=tmp_path / "worktrees",
        repositories=(
            RepositoryConfig(
                name="project",
                remote_url="git@example.test:owner/project.git",
                github_repository="owner/project",
                description="Repository used for lifecycle rendering tests.",
                author_name="Agent",
                author_email="agent@example.test",
            ),
        ),
        opencode=OpenCodeConfig(
            config_file=tmp_path / "opencode.json",
            xdg_config_home=tmp_path / "config",
            xdg_data_home=tmp_path / "data",
        ),
        github=GitHubConfig(agent_actor=GitHubLogin("agent")),
        coordinator=CoordinatorConfig(
            workspace_root=tmp_path / "coordinator",
            turn_timeout_seconds=1800,
            shutdown_timeout_seconds=30,
            orphan_retention_seconds=86400,
            retry_seconds=5,
            response_chunk_characters=3500,
            slack_post_interval_seconds=1,
            ingress=SlackEventsConfig(),
            slack=CoordinatorSlackConfig(
                workspace_id="T-test",
                channels=(CoordinatorSlackChannelConfig(channel_id="C-test", authorized_users=frozenset(("U-test",))),),
            ),
            opencode=OpenCodeConfig(
                server_url=HttpUrl("http://127.0.0.1:4098"),
                config_file=tmp_path / "coordinator-opencode.json",
                xdg_config_home=tmp_path / "coordinator-config",
                xdg_data_home=tmp_path / "coordinator-data",
            ),
        ),
        git=GitConfig(
            ssh_executable=tmp_path / "ssh",
            identity_file=tmp_path / "identity",
            known_hosts_file=tmp_path / "known_hosts",
        ),
    )
    output = StringIO()
    console = Console(file=output, force_terminal=True, color_system="standard", width=100)

    # WHEN
    console.print(render_status(status, config))
    rendered = output.getvalue()

    # THEN
    assert "Daemon lifecycle status" in rendered
    assert "Summary" in rendered
    assert "Timer" in rendered
    assert "Service" in rendered
    assert "Coordinator" in rendered
    assert "Coordinator ngrok" in rendered
    assert "enabled" in rendered
    assert "disabled" in rendered
    assert "Files" in rendered
    assert "Actions" in rendered
    assert "ocint daemon lch logs --lines 100" in rendered
    assert "ocint daemon lch logs --follow" in rendered
    assert re.search(r"\x1b\[[0-9;]*32m", rendered)
    assert re.search(r"\x1b\[[0-9;]*36m", rendered)
    assert re.search(r"\x1b\[[0-9;]*35m", rendered)
