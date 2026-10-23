from pathlib import Path

import pytest
from click.testing import CliRunner
from ocint.cli import main
from ocint.daemon.cli import open_daemon_app
from ocint.daemon.config import DaemonContext, DaemonSettings
from ocint.daemon.db import create_daemon_engine, migrate_daemon_db
from ocint.daemon.models import (
    GitHubLogin,
    ObservedMessage,
    PublicationRequest,
    PublicationResult,
    ReplyRequest,
    ThreadObservations,
)
from ocint.daemon.pull_request_job import PullRequestJobRequest
from ocint.daemon.pull_request_job.repository import PullRequestJobRepository
from ocint.daemon.slack import SlackAuth, SlackConfig
from ocint.presentation import default_cli_context


class FakeGitHubGateway:
    @property
    def source_prefix(self) -> str:
        return "github:"

    async def observe(self) -> ThreadObservations:
        return ThreadObservations(root=[])

    async def reply(self, request: ReplyRequest) -> ObservedMessage:
        raise AssertionError(request)

    async def publish(self, request: PublicationRequest) -> PublicationResult:
        raise AssertionError(request)


def test_lch_lists_and_inspects_jobs_while_daemon_is_inactive(tmp_path: Path) -> None:
    # GIVEN
    database = tmp_path / "daemon.sqlite"
    config = tmp_path / "daemon.toml"
    config.write_text(f'''database_path = "{database}"
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
    migrate_daemon_db(database)
    engine = create_daemon_engine(database)
    repository = PullRequestJobRepository(engine)
    jobs = [
        repository.submit(
            PullRequestJobRequest(
                idempotency_key=f"key-{number}",
                actor=GitHubLogin("maintainer"),
                repository="repo",
                title=f"Job title {number}",
                prompt="work",
            )
        )
        for number in range(12)
    ]
    engine.dispose()
    runner = CliRunner()
    environment = {"OCINT_DAEMON_CONFIG": str(config)}

    # WHEN
    listed = runner.invoke(main, ["daemon", "lch", "list"], env=environment)
    expanded = runner.invoke(main, ["daemon", "lch", "list", "--limit", "12"], env=environment)
    invalid = runner.invoke(main, ["daemon", "lch", "list", "--limit", "0"], env=environment)
    status = runner.invoke(main, ["daemon", "lch", "status", jobs[-1].id], env=environment)

    # THEN
    assert listed.exit_code == 0, listed.output
    assert jobs[0].id not in listed.output
    assert jobs[1].id not in listed.output
    assert all(job.id in listed.output for job in jobs[2:])
    assert "queued" in listed.output
    assert expanded.exit_code == 0, expanded.output
    assert all(job.id in expanded.output for job in jobs)
    assert invalid.exit_code == 2
    assert "x>=1" in invalid.output
    assert status.exit_code == 0, status.output
    assert "Daemon job status" in status.output
    assert jobs[-1].id in status.output
    assert "repo" in status.output
    assert "ocint: Job title 11" in status.output


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
    with (
        pytest.raises(ValueError, match="API_TOKEN"),
        open_daemon_app(
            DaemonContext.create(default_cli_context().output, tmp_path, {}, DaemonSettings(config=config)),
            FakeGitHubGateway(),
        ),
    ):
        pass


def test_slack_token_command_uses_hidden_stdin_and_preserves_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # GIVEN
    config_home = tmp_path / "config"
    managed = config_home / "ocint"
    managed.mkdir(parents=True)
    config = managed / "daemon.toml"
    config.write_text(
        f'''database_path = "{tmp_path / "control.sqlite"}"
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
[slack]
workspace_id = "T1"
[[slack.channels]]
channel_id = "C1"
repository = "repo"
authorized_users = ["U1"]
initial_oldest = "1753380000.123456"
'''
    )
    environment_file = managed / "daemon.env"
    environment_file.write_text("# preserve\nOTHER=value\nOCINT_DAEMON_API_TOKEN=api\n")
    environment_file.chmod(0o600)

    async def validate(_config: SlackConfig, token: str) -> SlackAuth:
        assert token == "xoxb-super-secret"
        return SlackAuth(user_id="UBOT", bot_id="BBOT", team_id="T1")

    monkeypatch.setattr("ocint.daemon.lch.cli.validate_configured_slack_token", validate)

    # WHEN
    result = CliRunner().invoke(
        main,
        ["daemon", "lch", "slack-token"],
        input="xoxb-super-secret\n",
        env={"OCINT_DAEMON_CONFIG": str(config), "XDG_CONFIG_HOME": str(config_home)},
    )

    # THEN
    assert result.exit_code == 0, result.output
    assert "xoxb-super-secret" not in result.output
    assert "Warning" not in result.output
    assert "Slack bot token:" not in result.output
    assert "workspace=T1" in result.output
    assert "bot_id=BBOT" in result.output
    assert environment_file.read_text() == (
        "# preserve\nOTHER=value\nOCINT_DAEMON_API_TOKEN=api\nOCINT_DAEMON_SLACK_BOT_TOKEN=xoxb-super-secret\n"
    )
