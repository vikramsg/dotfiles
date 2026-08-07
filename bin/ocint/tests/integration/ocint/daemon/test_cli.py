from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Never

import pytest
from click.testing import CliRunner
from ocint.cli import main
from ocint.daemon.cli import _run_coordinator, open_daemon_app
from ocint.daemon.config import DaemonContext, DaemonSettings
from ocint.daemon.coordinator import CoordinatorIngressConfig
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
from pydantic import SecretStr
from sqlalchemy import Engine


@pytest.fixture
def coordinator_toml(tmp_path: Path) -> str:
    return f'''[coordinator]
workspace_root = "{tmp_path / "coordinator"}"
turn_timeout_seconds = 1800
shutdown_timeout_seconds = 30
orphan_retention_seconds = 86400
retry_seconds = 5
response_chunk_characters = 3500
slack_post_interval_seconds = 1
[coordinator.ingress]
host = "127.0.0.1"
port = 8733
processing_timeout_seconds = 1.75
database_busy_timeout_ms = 1250
[coordinator.slack]
workspace_id = "T1"
[[coordinator.slack.channels]]
channel_id = "C1"
authorized_users = ["U1"]
[coordinator.opencode]
server_url = "http://127.0.0.1:4098"
config_file = "{tmp_path / "coordinator-opencode.json"}"
xdg_config_home = "{tmp_path / "coordinator-opencode-xdg"}"
xdg_data_home = "{tmp_path / "coordinator-opencode-data"}"
'''


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


def test_coordinator_run_command_is_discoverable() -> None:
    # GIVEN
    runner = CliRunner()

    # WHEN
    group = runner.invoke(main, ["daemon", "coordinator", "--help"])
    command = runner.invoke(main, ["daemon", "coordinator", "run", "--help"])

    # THEN
    assert group.exit_code == 0
    assert "run" in group.output
    assert command.exit_code == 0


@pytest.mark.asyncio
async def test_coordinator_requires_both_credentials_before_migrating(tmp_path: Path, coordinator_toml: str) -> None:
    # GIVEN
    database = tmp_path / "control.sqlite"
    config = tmp_path / "daemon.toml"
    config.write_text(
        f'''database_path = "{database}"
mirror_root = "{tmp_path / "mirrors"}"
worktree_root = "{tmp_path / "worktrees"}"
[[repositories]]
name = "repo"
description = "Repository for tests."
remote_url = "git@example.test:owner/repo.git"
github_repository = "owner/repo"
author_name = "Agent"
author_email = "agent@example.test"
[opencode]
config_file = "{tmp_path / "opencode.json"}"
xdg_config_home = "{tmp_path / "opencode-xdg"}"
xdg_data_home = "{tmp_path / "opencode-data"}"
[git]
ssh_executable = "/usr/bin/ssh"
identity_file = "{tmp_path / "identity"}"
known_hosts_file = "{tmp_path / "known-hosts"}"
[github]
agent_actor = "maintainer"
{coordinator_toml}
'''
    )
    context = DaemonContext.create(
        default_cli_context().output,
        tmp_path,
        {},
        DaemonSettings(
            config=config,
            slack_bot_token=SecretStr(""),
            slack_signing_secret=SecretStr(""),
        ),
    )

    # WHEN / THEN
    with pytest.raises(ValueError, match="SLACK_BOT_TOKEN"):
        await _run_coordinator(context)
    assert not database.exists()


@pytest.mark.asyncio
async def test_coordinator_validates_provisioned_runtime_before_startup_mutates_state(
    tmp_path: Path,
    coordinator_toml: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # GIVEN
    database = tmp_path / "control.sqlite"
    config = tmp_path / "daemon.toml"
    config.write_text(
        f'''database_path = "{database}"
mirror_root = "{tmp_path / "mirrors"}"
worktree_root = "{tmp_path / "worktrees"}"
[[repositories]]
name = "repo"
description = "Repository for tests."
remote_url = "git@example.test:owner/repo.git"
github_repository = "owner/repo"
author_name = "Agent"
author_email = "agent@example.test"
[opencode]
config_file = "{tmp_path / "opencode.json"}"
xdg_config_home = "{tmp_path / "opencode-xdg"}"
xdg_data_home = "{tmp_path / "opencode-data"}"
[git]
ssh_executable = "/usr/bin/ssh"
identity_file = "{tmp_path / "identity"}"
known_hosts_file = "{tmp_path / "known-hosts"}"
[github]
agent_actor = "maintainer"
{coordinator_toml}
'''
    )
    context = DaemonContext.create(
        default_cli_context().output,
        tmp_path,
        {},
        DaemonSettings(
            config=config,
            slack_bot_token=SecretStr("xoxb-token"),
            slack_signing_secret=SecretStr("signing-secret"),
        ),
    )

    def reject_runtime(_context: DaemonContext, _config: object) -> None:
        raise RuntimeError("coordinator policy drift")

    monkeypatch.setattr("ocint.daemon.cli.validate_coordinator_runtime", reject_runtime)

    # WHEN / THEN
    with pytest.raises(RuntimeError, match="policy drift"):
        await _run_coordinator(context)
    assert not database.exists()


@pytest.mark.asyncio
async def test_coordinator_composes_ingress_processing_and_database_timeouts(
    tmp_path: Path,
    coordinator_toml: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # GIVEN
    database = tmp_path / "control.sqlite"
    config = tmp_path / "daemon.toml"
    config.write_text(
        f'''database_path = "{database}"
mirror_root = "{tmp_path / "mirrors"}"
worktree_root = "{tmp_path / "worktrees"}"
[[repositories]]
name = "repo"
description = "Repository for tests."
remote_url = "git@example.test:owner/repo.git"
github_repository = "owner/repo"
author_name = "Agent"
author_email = "agent@example.test"
[opencode]
config_file = "{tmp_path / "opencode.json"}"
xdg_config_home = "{tmp_path / "opencode-xdg"}"
xdg_data_home = "{tmp_path / "opencode-data"}"
[git]
ssh_executable = "/usr/bin/ssh"
identity_file = "{tmp_path / "identity"}"
known_hosts_file = "{tmp_path / "known-hosts"}"
[github]
agent_actor = "maintainer"
{coordinator_toml}
'''
    )
    context = DaemonContext.create(
        default_cli_context().output,
        tmp_path,
        {},
        DaemonSettings(
            config=config,
            slack_bot_token=SecretStr("xoxb-token"),
            slack_signing_secret=SecretStr("signing-secret"),
        ),
    )
    observed: dict[str, float] = {}
    real_create_engine = create_daemon_engine

    async def validate_slack(_config: object, _token: str) -> None:
        return

    def create_engine(path: Path, busy_timeout_ms: int = 2_000) -> Engine:
        observed["database_busy_timeout_ms"] = busy_timeout_ms
        return real_create_engine(path, busy_timeout_ms)

    @asynccontextmanager
    async def delivery(_token: str) -> AsyncIterator[object]:
        yield object()

    def create_events_app(ingress: CoordinatorIngressConfig, *_arguments: object) -> Never:
        observed["processing_timeout_seconds"] = ingress.processing_timeout_seconds
        raise RuntimeError("composition observed")

    monkeypatch.setattr("ocint.daemon.cli.validate_coordinator_runtime", lambda _context, _config: None)
    monkeypatch.setattr("ocint.daemon.cli.validate_coordinator_slack_access", validate_slack)
    monkeypatch.setattr("ocint.daemon.cli.create_daemon_engine", create_engine)
    monkeypatch.setattr("ocint.daemon.cli.open_slack_coordinator_delivery", delivery)
    monkeypatch.setattr("ocint.daemon.cli.create_slack_events_app", create_events_app)

    # WHEN / THEN
    with pytest.raises(RuntimeError, match="composition observed"):
        await _run_coordinator(context)
    assert observed == {
        "database_busy_timeout_ms": 1250,
        "processing_timeout_seconds": 1.75,
    }


def test_lch_lists_and_inspects_jobs_while_daemon_is_inactive(tmp_path: Path, coordinator_toml: str) -> None:
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
description = "Repository for tests."
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
{coordinator_toml}
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


def test_app_factory_requires_api_token_before_state_creation(tmp_path: Path, coordinator_toml: str) -> None:
    # GIVEN
    config = tmp_path / "daemon.toml"
    config.write_text(f'''database_path = "{tmp_path / "control.sqlite"}"
mirror_root = "{tmp_path / "mirrors"}"
worktree_root = "{tmp_path / "worktrees"}"
[[repositories]]
name = "repo"
remote_url = "git@example.test:owner/repo.git"
github_repository = "owner/repo"
description = "Repository for tests."
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
{coordinator_toml}
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
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, coordinator_toml: str
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
description = "Repository for tests."
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
{coordinator_toml}
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
