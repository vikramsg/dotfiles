from pathlib import Path

import pytest
from ocint.daemon.config import DaemonConfig, DaemonSettings, OpenCodeConfig, RepositoryConfig
from pydantic import ValidationError


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
    with pytest.raises(ValidationError, match=r"1\.17\.20"):
        OpenCodeConfig.model_validate(
            {
                "expected_version": "2.0.0",
                "config_file": tmp_path / "opencode.json",
                "xdg_config_home": tmp_path / "config",
                "xdg_data_home": tmp_path / "data",
            }
        )
