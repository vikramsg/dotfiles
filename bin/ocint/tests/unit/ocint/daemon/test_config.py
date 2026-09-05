from pathlib import Path

import pytest
from ocint.daemon.config import (
    DaemonConfig,
    DaemonContext,
    DaemonSettings,
    LifecycleConfig,
    LoggingConfig,
    RepositoryConfig,
)
from ocint.daemon.opencode import OpenCodeConfig
from ocint.daemon.slack import SlackConfig
from ocint.presentation import default_cli_context
from pydantic import ValidationError


def test_slack_config_requires_safe_boundary_and_unique_channels() -> None:
    # GIVEN
    channel = {
        "channel_id": "C1",
        "repository": "repo",
        "authorized_users": ["U1"],
        "initial_oldest": "1753380000.123456",
    }

    # WHEN / THEN
    config = SlackConfig.model_validate({"workspace_id": "T1", "channels": [channel]})
    assert config.channels[0].authorized_users == frozenset(("U1",))
    with pytest.raises(ValidationError, match="initial_oldest"):
        SlackConfig.model_validate(
            {
                "workspace_id": "T1",
                "channels": [{key: value for key, value in channel.items() if key != "initial_oldest"}],
            }
        )
    with pytest.raises(ValidationError, match="unique"):
        SlackConfig.model_validate({"workspace_id": "T1", "channels": [channel, channel]})


def test_slack_manifest_is_private_polling_only() -> None:
    # GIVEN
    manifest = (Path(__file__).parents[4] / "config" / "slack-app-manifest.yaml").read_text()

    # WHEN
    scopes = {line.removeprefix("      - ").strip() for line in manifest.splitlines() if line.startswith("      - ")}

    # THEN
    assert scopes == {"groups:history", "chat:write", "reactions:write"}
    assert "socket_mode_enabled: false" in manifest
    assert "event_subscriptions" not in manifest
    assert "slash_commands" not in manifest
    assert "interactivity" not in manifest


def test_config_resolves_repository_and_rejects_duplicate_names(tmp_path: Path) -> None:
    # GIVEN
    raw = {
        "database_path": tmp_path / "control.sqlite",
        "mirror_root": tmp_path / "mirrors",
        "worktree_root": tmp_path / "worktrees",
        "repositories": [
            {
                "name": "repo",
                "remote_url": "git@example:repo.git",
                "github_repository": "owner/repo",
                "author_name": "Agent",
                "author_email": "agent@example.test",
                "actors": ["actor"],
                "checks": [["just", "check"]],
            }
        ],
        "opencode": {
            "config_file": tmp_path / "opencode-xdg" / "opencode" / "opencode.json",
            "xdg_config_home": tmp_path / "opencode-xdg",
            "xdg_data_home": tmp_path / "data",
        },
        "git": {
            "ssh_executable": tmp_path / "ssh",
            "identity_file": tmp_path / "identity",
            "known_hosts_file": tmp_path / "known_hosts",
        },
        "github": {"agent_actor": "maintainer"},
    }

    # WHEN
    config = DaemonConfig.model_validate(raw)

    # THEN
    assert config.repository("repo").author_name == "Agent"
    assert isinstance(config.repositories, tuple)
    assert isinstance(config.repository("repo").actors, frozenset)
    assert isinstance(config.repository("repo").checks, tuple)
    assert isinstance(config.repository("repo").checks[0], tuple)
    with pytest.raises(ValidationError, match="unique"):
        DaemonConfig.model_validate({**raw, "repositories": [*raw["repositories"], *raw["repositories"]]})


@pytest.mark.parametrize("remote", ["git@example.test:owner/repo.git", "ssh://git@example.test/owner/repo.git"])
def test_repository_accepts_ssh_remotes(remote: str) -> None:
    # GIVEN / WHEN
    repository = RepositoryConfig(
        name="repo",
        remote_url=remote,
        github_repository="owner/repo",
        author_name="Agent",
        author_email="agent@example.test",
    )

    # THEN
    assert repository.remote_url == remote


@pytest.mark.parametrize(
    "remote",
    [
        "https://example.test/owner/repo.git",
        "http://example.test/owner/repo.git",
        "file:///tmp/repo.git",
        "/tmp/repo.git",
        "../repo.git",
    ],
)
def test_repository_rejects_non_ssh_remotes(remote: str) -> None:
    # GIVEN / WHEN / THEN
    with pytest.raises(ValidationError, match="must use SSH"):
        RepositoryConfig(
            name="repo",
            remote_url=remote,
            github_repository="owner/repo",
            author_name="Agent",
            author_email="agent@example.test",
        )


def test_settings_are_constructible_without_credentials(tmp_path: Path) -> None:
    # GIVEN
    home = tmp_path / "home"

    # WHEN
    settings = DaemonSettings(xdg_config_home=home / "config")

    # THEN
    assert settings.config_path(home) == home / "config" / "ocint" / "daemon.toml"


def test_opencode_expected_version_rejects_every_other_literal(tmp_path: Path) -> None:
    # GIVEN / WHEN / THEN
    with pytest.raises(ValidationError, match=r"1\.18\.15"):
        OpenCodeConfig.model_validate(
            {
                "expected_version": "2.0.0",
                "config_file": tmp_path / "opencode.json",
                "xdg_config_home": tmp_path / "config",
                "xdg_data_home": tmp_path / "data",
            }
        )


def test_lifecycle_and_logging_defaults_are_typed_and_overridable(tmp_path: Path) -> None:
    # GIVEN
    raw = {
        "database_path": tmp_path / "control.sqlite",
        "mirror_root": tmp_path / "mirrors",
        "worktree_root": tmp_path / "worktrees",
        "repositories": [
            {
                "name": "repo",
                "remote_url": "git@example.test:owner/repo.git",
                "github_repository": "owner/repo",
                "author_name": "Agent",
                "author_email": "agent@example.test",
            }
        ],
        "opencode": {
            "config_file": tmp_path / "opencode.json",
            "xdg_config_home": tmp_path / "config",
            "xdg_data_home": tmp_path / "data",
        },
        "github": {"agent_actor": "maintainer"},
        "git": {
            "ssh_executable": tmp_path / "ssh",
            "identity_file": tmp_path / "identity",
            "known_hosts_file": tmp_path / "known_hosts",
        },
    }

    # WHEN
    defaulted = DaemonConfig.model_validate(raw)
    overridden = DaemonConfig.model_validate(
        {
            **raw,
            "lifecycle": {"startup_delay_seconds": 75, "inactive_interval_seconds": 901},
            "logging": {"max_bytes": 2048, "backup_count": 2},
        }
    )

    # THEN
    assert defaulted.lifecycle == LifecycleConfig()
    assert defaulted.logging == LoggingConfig()
    assert overridden.lifecycle.startup_delay_seconds == 75
    assert overridden.lifecycle.inactive_interval_seconds == 901
    assert overridden.logging.max_bytes == 2048
    assert overridden.logging.backup_count == 2
    with pytest.raises(ValidationError):
        LifecycleConfig(startup_delay_seconds=0)
    with pytest.raises(ValidationError):
        LoggingConfig(backup_count=0)


def test_daemon_context_loads_configuration_once_per_command(tmp_path: Path) -> None:
    # GIVEN
    config = tmp_path / "daemon.toml"
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
xdg_config_home = "{tmp_path / "config"}"
xdg_data_home = "{tmp_path / "data"}"
[github]
agent_actor = "maintainer"
[git]
ssh_executable = "{tmp_path / "ssh"}"
identity_file = "{tmp_path / "identity"}"
known_hosts_file = "{tmp_path / "known_hosts"}"
'''
    )
    context = DaemonContext.create(
        default_cli_context().output,
        tmp_path,
        {"XDG_STATE_HOME": str(tmp_path / "state")},
        DaemonSettings(config=config),
    )

    # WHEN
    first = context.config()
    config.write_text("not = [valid")
    second = context.config()

    # THEN
    assert first is second
    assert first.lifecycle == LifecycleConfig()
