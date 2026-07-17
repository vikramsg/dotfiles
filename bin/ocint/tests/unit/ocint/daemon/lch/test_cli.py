import socket
import stat
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

import click
import pytest
from ocint.daemon.lch.cli import (
    RestrictedOpenCodeConfig,
    ensure_auth_symlink,
    existing_github_token,
    require_available_loopback_port,
    restricted_opencode_config,
    write_private_file,
)
from ocint.daemon.lch.systemd import CommandResult


@dataclass
class TokenRunner:
    calls: list[list[str]] = field(default_factory=list)

    def run(self, arguments: Sequence[str]) -> CommandResult:
        self.calls.append(list(arguments))
        return CommandResult(stdout="existing-token\n")


def test_restricted_opencode_config_keeps_only_selected_provider_model(tmp_path: Path) -> None:
    # GIVEN
    source = tmp_path / "opencode.json"
    source.write_text(
        """{
  "model": "azure-cognitive-services/gpt-5.6-sol",
  "instructions": ["global-rules.md"],
  "plugin": ["global-plugin"],
  "agent": {"build": {"prompt": "global-agent"}},
  "provider": {
    "azure-cognitive-services": {
      "options": {"baseURL": "https://example.test/openai/v1", "apiKey": "must-not-copy"},
      "models": {
        "gpt-5.6-sol": {
          "id": "gpt-5.6-sol",
          "name": "gpt-5.6-sol",
          "options": {"reasoningEffort": "medium", "reasoningSummary": "auto"},
          "modalities": {"input": ["text", "image"], "output": ["text"]}
        },
        "other": {"id": "other", "name": "other"}
      }
    },
    "global-provider": {"models": {"global": {"id": "global", "name": "global"}}}
  }
}
"""
    )

    # WHEN
    rendered = restricted_opencode_config(source, tmp_path / "worktrees")
    restricted = RestrictedOpenCodeConfig.model_validate_json(rendered)

    # THEN
    assert restricted.model == "azure-cognitive-services/gpt-5.6-sol"
    assert set(restricted.provider) == {"azure-cognitive-services"}
    assert set(restricted.provider["azure-cognitive-services"].models) == {"gpt-5.6-sol"}
    assert restricted.provider["azure-cognitive-services"].options.base_url == "https://example.test/openai/v1"
    assert restricted.instructions == []
    assert restricted.plugin == []
    assert restricted.agent == {}
    assert "must-not-copy" not in rendered
    assert "global-rules" not in rendered
    assert "global-plugin" not in rendered
    assert "global-agent" not in rendered


def test_private_file_replacement_is_atomic_mode_0600_and_idempotent(tmp_path: Path) -> None:
    # GIVEN
    destination = tmp_path / "daemon.env"
    write_private_file(destination, "OCINT_DAEMON_API_TOKEN=preserved\n")

    # WHEN
    write_private_file(
        destination,
        "OCINT_DAEMON_API_TOKEN=preserved\nOCINT_DAEMON_GITHUB_TOKEN=refreshed\n",
    )

    # THEN
    assert stat.S_IMODE(destination.stat().st_mode) == 0o600
    assert destination.read_text().startswith("OCINT_DAEMON_API_TOKEN=preserved\n")
    assert list(tmp_path.glob(".daemon.env.*")) == []


def test_github_token_lookup_never_refreshes_authentication() -> None:
    # GIVEN
    runner = TokenRunner()

    # WHEN
    token = existing_github_token(runner)

    # THEN
    assert token == "existing-token"
    assert runner.calls == [["gh", "auth", "token", "--hostname", "github.com"]]
    assert all("refresh" not in command for command in runner.calls)


def test_isolated_opencode_data_uses_safe_auth_symlink(tmp_path: Path) -> None:
    # GIVEN
    source = tmp_path / "shared" / "opencode" / "auth.json"
    source.parent.mkdir(parents=True)
    source.write_text("credential")
    source.chmod(0o600)
    isolated = tmp_path / "managed" / "opencode-data"

    # WHEN
    target = ensure_auth_symlink(source, isolated)

    # THEN
    assert target.is_symlink()
    assert target.resolve() == source.resolve()
    assert target.read_text() == "credential"
    assert stat.S_IMODE(isolated.stat().st_mode) == 0o700
    assert stat.S_IMODE(target.parent.stat().st_mode) == 0o700
    assert stat.S_IMODE(source.stat().st_mode) == 0o600


def test_isolated_opencode_data_rejects_existing_non_symlink_auth(tmp_path: Path) -> None:
    # GIVEN
    source = tmp_path / "shared" / "opencode" / "auth.json"
    source.parent.mkdir(parents=True)
    source.write_text("credential")
    source.chmod(0o600)
    target = tmp_path / "managed" / "opencode-data" / "opencode" / "auth.json"
    target.parent.mkdir(parents=True)
    target.write_text("unsafe-copy")

    # WHEN / THEN
    with pytest.raises(click.ClickException, match="auth link is unsafe"):
        ensure_auth_symlink(source, tmp_path / "managed" / "opencode-data")


def test_private_opencode_port_must_be_available() -> None:
    # GIVEN
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        occupied_port = listener.getsockname()[1]

        # WHEN / THEN
        with pytest.raises(click.ClickException, match=str(occupied_port)):
            require_available_loopback_port(occupied_port)
