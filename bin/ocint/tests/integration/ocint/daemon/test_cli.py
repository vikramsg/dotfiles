from pathlib import Path

import pytest
from ocint.daemon.cli import create_daemon_app
from ocint.daemon.config import DaemonContext, DaemonSettings
from ocint.presentation import default_cli_context


def test_app_factory_requires_api_token_before_state_creation(tmp_path: Path) -> None:
    # GIVEN
    config = tmp_path / "daemon.toml"
    config.write_text(f'''database_path = "{tmp_path / "control.sqlite"}"
mirror_root = "{tmp_path / "mirrors"}"
worktree_root = "{tmp_path / "worktrees"}"
[[repositories]]
name = "repo"
remote_url = "git@example.test:owner/repo.git"
github_repository = "owner/repo"
author_name = "Agent"
author_email = "agent@example.test"
[opencode]
config_file = "{tmp_path / "opencode.json"}"
xdg_config_home = "{tmp_path / "opencode-xdg"}"
xdg_data_home = "{tmp_path / "data"}"
[git]
ssh_executable = "/usr/bin/ssh"
identity_file = "{tmp_path / "identity"}"
known_hosts_file = "{tmp_path / "known_hosts"}"
[github]
agent_actor = "maintainer"
''')

    # WHEN / THEN
    with pytest.raises(ValueError, match="API_TOKEN"):
        create_daemon_app(
            DaemonContext.create(default_cli_context().output, tmp_path, {}, DaemonSettings(config=config))
        )
