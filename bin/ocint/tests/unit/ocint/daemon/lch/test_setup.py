import os
import socket
import stat
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

import click
import pytest
from ocint.daemon.config import DaemonContext, DaemonSettings, LifecycleConfig, LoggingConfig
from ocint.daemon.lch.setup import (
    CoordinatorRestrictedOpenCodeConfig,
    OpenCodeSourceConfig,
    RestrictedOpenCodeConfig,
    coordinator_policy_bytes,
    coordinator_restricted_opencode_config,
    daemon_toml,
    discover,
    discovered_daemon_config,
    ensure_auth_symlink,
    existing_github_token,
    load_coordinator_policy,
    load_policy,
    policy_bytes,
    provision_configured_coordinator_runtime,
    require_available_loopback_port,
    restricted_opencode_config,
    setup,
    upsert_private_environment,
    validate_coordinator_runtime,
    write_private_file,
)
from ocint.daemon.lch.systemd import CommandResult, SystemdLifecycle, SystemdPaths
from ocint.presentation import default_cli_context


@dataclass
class TokenRunner:
    calls: list[list[str]] = field(default_factory=list)
    environments: list[Mapping[str, str]] = field(default_factory=list)

    def run(self, arguments: Sequence[str]) -> CommandResult:
        self.calls.append(list(arguments))
        return CommandResult(stdout="existing-token\n")

    def run_isolated(self, arguments: Sequence[str], environment: Mapping[str, str]) -> CommandResult:
        self.environments.append(environment)
        return self.run(arguments)

    def run_interactive(self, arguments: Sequence[str], environment: Mapping[str, str]) -> None:
        _ = (arguments, environment)
        raise AssertionError("not used")


@dataclass
class DiscoveryRunner:
    checkout: Path
    ssh: Path
    identities: tuple[Path, ...]
    known_hosts: Path
    repository: str = "example-org/project"
    version: str = "1.18.15"
    push_urls: tuple[str, ...] = ("git@github.com:example-org/project.git",)
    core_ssh_command: str = ""
    isolated_calls: list[tuple[tuple[str, ...], Mapping[str, str]]] = field(default_factory=list)

    def run(self, arguments: Sequence[str]) -> CommandResult:
        command = tuple(arguments)
        if command[-2:] == ("daemon", "--help"):
            return CommandResult(stdout="Commands:\n  run\n  doctor\n  lch\n")
        if command[-3:] == ("daemon", "lch", "--help"):
            return CommandResult(
                stdout="Commands:\n  apply\n  attach\n  lifecycle\n  list\n  logs\n  setup\n  slack-token\n  status\n  uninstall\n"
            )
        if command[0] == "loginctl":
            return CommandResult(stdout="yes\n")
        if command[0] == "systemctl":
            return CommandResult()
        if command[-1] == "version":
            return CommandResult(stdout="ngrok version 3.31.0\n")
        raise AssertionError(command)

    def run_isolated(self, arguments: Sequence[str], environment: Mapping[str, str]) -> CommandResult:
        command = tuple(arguments)
        self.isolated_calls.append((command, environment))
        if command == ("git", "-C", str(self.checkout), "rev-parse", "--show-toplevel"):
            return CommandResult(stdout=f"{self.checkout}\n")
        if command == ("gh", "api", "--hostname", "github.com", "user"):
            return CommandResult(stdout='{"login":"maintainer"}')
        if command == (
            "gh",
            "repo",
            "view",
            "example-org/project",
            "--json",
            "nameWithOwner,defaultBranchRef",
        ):
            return CommandResult(stdout=f'{{"nameWithOwner":"{self.repository}","defaultBranchRef":{{"name":"main"}}}}')
        if command == ("gh", "auth", "token", "--hostname", "github.com"):
            return CommandResult(stdout="github-secret\n")
        if command == ("git", "-C", str(self.checkout), "branch", "--show-current"):
            return CommandResult(stdout="main\n")
        if command[:4] == ("git", "-C", str(self.checkout), "config"):
            if command[-1] == "core.sshCommand":
                return CommandResult(stdout=self.core_ssh_command)
            return CommandResult()
        if command == (
            "git",
            "-C",
            str(self.checkout),
            "remote",
            "get-url",
            "--push",
            "--all",
            "origin",
        ):
            return CommandResult(stdout="".join(f"{item}\n" for item in self.push_urls))
        if command == ("git", "-C", str(self.checkout), "var", "GIT_AUTHOR_IDENT"):
            return CommandResult(stdout="Example Author <author@example.test> 1784300000 +0000\n")
        if command in {
            (str(self.ssh), "-G", "-l", "git", "github.com"),
            (str(self.ssh), "-o", "IdentitiesOnly=yes", "-G", "-l", "git", "github.com"),
            (str(self.ssh), "-G", "-p", "2222", "-l", "deploy", "github.com"),
        }:
            identity_lines = "".join(f"identityfile {item}\n" for item in self.identities)
            return CommandResult(stdout=f"{identity_lines}userknownhostsfile {self.known_hosts}\n")
        if command[-1] == "--version":
            return CommandResult(stdout=f"{self.version}\n")
        raise AssertionError(command)

    def run_interactive(self, arguments: Sequence[str], environment: Mapping[str, str]) -> None:
        _ = (arguments, environment)
        raise AssertionError("not used")


@dataclass
class DiscoveryFixture:
    runner: DiscoveryRunner
    lifecycle: SystemdLifecycle
    checkout: Path
    home: Path
    managed_config: Path
    context: DaemonContext


@pytest.fixture
def discovery_fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> DiscoveryFixture:
    # GIVEN
    checkout = tmp_path / "project"
    checkout.mkdir()
    home = tmp_path / "home"
    config_home = home / "config"
    data_home = home / "data"
    state_home = home / "state"
    source_config = config_home / "opencode" / "opencode.json"
    source_config.parent.mkdir(parents=True)
    source_config.write_text(
        '{"model":"example-provider/example-model","provider":{"example-provider":'
        '{"models":{"example-model":{"id":"example-model","name":"Example"}}}}}'
    )
    auth = data_home / "opencode" / "auth.json"
    auth.parent.mkdir(parents=True)
    auth.write_text("auth-secret")
    auth.chmod(0o600)
    ssh_directory = home / ".ssh"
    ssh_directory.mkdir(parents=True)
    identity = ssh_directory / "project-key"
    identity.write_text("private-key")
    identity.chmod(0o600)
    known_hosts = ssh_directory / "known_hosts"
    known_hosts.write_text("github.com key")
    binary_directory = tmp_path / "bin"
    binary_directory.mkdir()
    ssh = binary_directory / "ssh"
    ocint = binary_directory / "ocint"
    opencode = binary_directory / "opencode"
    ngrok = binary_directory / "ngrok"
    for executable in (ssh, ocint, opencode, ngrok):
        executable.write_text("#!/bin/sh\nexit 0\n")
        executable.chmod(0o755)
    monkeypatch.setenv("PATH", str(binary_directory))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(config_home))
    monkeypatch.setenv("XDG_DATA_HOME", str(data_home))
    monkeypatch.setenv("XDG_STATE_HOME", str(state_home))
    monkeypatch.setenv("OCINT_NGROK_URL", "https://static.example.test")
    monkeypatch.setattr("ocint.daemon.lch.setup.require_available_loopback_port", lambda _port: None)
    paths = SystemdPaths(
        directory=config_home / "systemd" / "user",
        environment_file=config_home / "ocint" / "daemon.env",
        config_home=config_home,
        data_home=data_home,
        state_home=state_home,
        daemon_config=config_home / "ocint" / "daemon.toml",
        home=home,
    )
    runner = DiscoveryRunner(checkout, ssh.resolve(), (identity,), known_hosts)
    context = DaemonContext.create(
        default_cli_context().output,
        home,
        dict(os.environ),
        DaemonSettings(config=config_home / "ocint" / "daemon.toml"),
    )
    return DiscoveryFixture(runner, SystemdLifecycle(paths, runner), checkout, home, config_home / "ocint", context)


def test_discovery_resolves_checkout_github_git_ssh_and_opencode(discovery_fixture: DiscoveryFixture) -> None:
    # GIVEN / WHEN
    result = discover(
        discovery_fixture.runner,
        discovery_fixture.lifecycle,
        discovery_fixture.checkout,
        discovery_fixture.context,
    )

    # THEN
    assert result.login == "maintainer"
    assert result.github_repository == "example-org/project"
    assert result.remote_url == "git@github.com:example-org/project.git"
    assert result.author.email == "author@example.test"
    assert result.ssh.identity_file.name == "project-key"
    assert result.opencode.model == "example-provider/example-model"
    assert result.github_token == "github-secret"
    assert result.opencode.version == "1.18.15"
    rendered = daemon_toml(discovered_daemon_config(result, (LifecycleConfig(), LoggingConfig())))
    assert rendered.count('expected_version = "1.18.15"') == 2
    assert 'description = "Personal configuration for OpenCode, Neovim, tmux, and terminals."' in rendered
    assert 'workspace_id = "T021N0EQ3JQ"' in rendered
    assert 'channel_id = "C0955FD2FK4"' in rendered
    assert 'authorized_users = ["U067EG8278R"]' in rendered
    assert '[api]\nhost = "127.0.0.1"\nport = 8732' in rendered
    assert 'server_url = "http://127.0.0.1:4098/"' in rendered
    assert str(result.paths.coordinator_effective_opencode_config) in rendered
    gh_commands = [command for command, _environment in discovery_fixture.runner.isolated_calls if command[0] == "gh"]
    assert gh_commands == [
        ("gh", "api", "--hostname", "github.com", "user"),
        ("gh", "repo", "view", "example-org/project", "--json", "nameWithOwner,defaultBranchRef"),
        ("gh", "auth", "token", "--hostname", "github.com"),
    ]
    assert (str(discovery_fixture.runner.ssh), "-G", "-l", "git", "github.com") in [
        command for command, _environment in discovery_fixture.runner.isolated_calls
    ]
    assert not discovery_fixture.managed_config.exists()


def test_generated_daemon_toml_round_trips_selected_turn_retry_budget(
    discovery_fixture: DiscoveryFixture,
) -> None:
    # GIVEN
    discovered = discover(
        discovery_fixture.runner,
        discovery_fixture.lifecycle,
        discovery_fixture.checkout,
        discovery_fixture.context,
    )
    generated = discovered_daemon_config(discovered, (LifecycleConfig(), LoggingConfig()))
    selected = generated.model_copy(
        update={"coordinator": generated.coordinator.model_copy(update={"max_turn_retries": 11})}
    )
    discovery_fixture.context.config_path.parent.mkdir(parents=True)
    discovery_fixture.context.config_path.write_text(daemon_toml(selected))

    # WHEN
    loaded = discovery_fixture.context.config()

    # THEN
    assert loaded.coordinator.max_turn_retries == 11


def test_discovery_passes_explicit_ssh_url_user_and_port_to_ssh_config(
    discovery_fixture: DiscoveryFixture,
) -> None:
    # GIVEN
    discovery_fixture.runner.push_urls = ("ssh://deploy@github.com:2222/example-org/project.git",)

    # WHEN
    result = discover(
        discovery_fixture.runner,
        discovery_fixture.lifecycle,
        discovery_fixture.checkout,
        discovery_fixture.context,
    )

    # THEN
    assert result.github_repository == "example-org/project"
    assert (str(discovery_fixture.runner.ssh), "-G", "-p", "2222", "-l", "deploy", "github.com") in [
        command for command, _environment in discovery_fixture.runner.isolated_calls
    ]


def test_discovery_ignores_ambient_github_and_git_config_overrides(
    discovery_fixture: DiscoveryFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # GIVEN
    monkeypatch.setenv("GH_REPO", "ambient/repository")
    monkeypatch.setenv("GH_HOST", "example.invalid")
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", "remote.pushDefault")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", "ambient")
    discovery_fixture.context.environment.update(
        {
            "GH_REPO": "ambient/repository",
            "GH_HOST": "example.invalid",
            "GIT_CONFIG_COUNT": "1",
            "GIT_CONFIG_KEY_0": "remote.pushDefault",
            "GIT_CONFIG_VALUE_0": "ambient",
        }
    )

    # WHEN
    result = discover(
        discovery_fixture.runner,
        discovery_fixture.lifecycle,
        discovery_fixture.checkout,
        discovery_fixture.context,
    )

    # THEN
    assert result.github_repository == "example-org/project"
    for _command, environment in discovery_fixture.runner.isolated_calls:
        assert "GH_REPO" not in environment
        assert "GH_HOST" not in environment
        assert "GIT_CONFIG_COUNT" not in environment


@pytest.mark.parametrize("variable", ["GIT_SSH_COMMAND", "GIT_SSH"])
def test_discovery_rejects_ambient_git_ssh_precedence_override(
    discovery_fixture: DiscoveryFixture,
    monkeypatch: pytest.MonkeyPatch,
    variable: str,
) -> None:
    # GIVEN
    monkeypatch.setenv(variable, "ssh -i /tmp/ambient-key")
    discovery_fixture.context.environment[variable] = "ssh -i /tmp/ambient-key"

    # WHEN / THEN
    with pytest.raises(click.ClickException, match="unset GIT_SSH_COMMAND and GIT_SSH"):
        discover(
            discovery_fixture.runner,
            discovery_fixture.lifecycle,
            discovery_fixture.checkout,
            discovery_fixture.context,
        )
    assert not discovery_fixture.managed_config.exists()


def test_discovery_uses_safe_core_ssh_command_after_rejecting_environment_precedence(
    discovery_fixture: DiscoveryFixture,
) -> None:
    # GIVEN
    discovery_fixture.runner.core_ssh_command = f"{discovery_fixture.runner.ssh} -o IdentitiesOnly=yes"

    # WHEN
    result = discover(
        discovery_fixture.runner,
        discovery_fixture.lifecycle,
        discovery_fixture.checkout,
        discovery_fixture.context,
    )

    # THEN
    assert result.ssh.executable == discovery_fixture.runner.ssh
    assert (
        str(discovery_fixture.runner.ssh),
        "-o",
        "IdentitiesOnly=yes",
        "-G",
        "-l",
        "git",
        "github.com",
    ) in [command for command, _environment in discovery_fixture.runner.isolated_calls]


def test_discovery_rejects_multiple_push_urls_before_github(discovery_fixture: DiscoveryFixture) -> None:
    # GIVEN
    discovery_fixture.runner.push_urls = (
        "git@github.com:example-org/project.git",
        "git@github.com:example-org/backup.git",
    )

    # WHEN / THEN
    with pytest.raises(click.ClickException, match="exactly one push URL"):
        discover(
            discovery_fixture.runner,
            discovery_fixture.lifecycle,
            discovery_fixture.checkout,
            discovery_fixture.context,
        )
    assert not any(command[0] == "gh" for command, _environment in discovery_fixture.runner.isolated_calls)


def test_discovery_rejects_wrong_opencode_version_before_writes(discovery_fixture: DiscoveryFixture) -> None:
    # GIVEN
    discovery_fixture.runner.version = "2.0.0"

    # WHEN / THEN
    with pytest.raises(click.ClickException, match=r"1\.18\.15 is required; found 2\.0\.0"):
        discover(
            discovery_fixture.runner,
            discovery_fixture.lifecycle,
            discovery_fixture.checkout,
            discovery_fixture.context,
        )
    assert not discovery_fixture.managed_config.exists()


def test_setup_uses_only_the_validated_policy_and_provider_snapshot(
    discovery_fixture: DiscoveryFixture,
) -> None:
    # GIVEN
    discovered = discover(
        discovery_fixture.runner,
        discovery_fixture.lifecycle,
        discovery_fixture.checkout,
        discovery_fixture.context,
    )
    discovered.opencode.source_config.write_text(
        '{"model":"changed-provider/changed-model","provider":{"changed-provider":'
        '{"options":{"apiKey":"late-secret"},'
        '"models":{"changed-model":{"id":"changed-model","name":"Changed"}}}}}'
    )

    # WHEN
    setup(discovered, discovery_fixture.lifecycle)

    # THEN
    effective = discovered.paths.effective_opencode_config.read_text()
    assert effective == discovered.effective_opencode_payload
    assert "changed-provider" not in effective
    assert "late-secret" not in effective
    assert discovered.paths.configuration.read_text().count('expected_version = "1.18.15"') == 2
    assert discovered.paths.coordinator_effective_opencode_config.read_text() == (
        discovered.coordinator_effective_opencode_payload
    )
    assert stat.S_IMODE(discovered.paths.coordinator_effective_opencode_config.stat().st_mode) == 0o600
    assert stat.S_IMODE(discovered.paths.coordinator_workspace.stat().st_mode) == 0o700
    assert not (discovered.paths.coordinator_workspace / "AGENTS.md").exists()
    assert not (discovered.paths.coordinator_workspace / "repositories.json").exists()
    coordinator_auth = discovered.paths.coordinator_isolated_data_home / "opencode" / "auth.json"
    assert coordinator_auth.is_symlink()
    assert coordinator_auth.resolve() == discovered.opencode.auth_source.resolve()
    assert stat.S_IMODE(discovered.paths.coordinator_isolated_config_home.stat().st_mode) == 0o700
    assert stat.S_IMODE(discovered.paths.coordinator_isolated_data_home.stat().st_mode) == 0o700


def test_setup_losslessly_refreshes_managed_tokens(discovery_fixture: DiscoveryFixture) -> None:
    # GIVEN
    discovered = discover(
        discovery_fixture.runner,
        discovery_fixture.lifecycle,
        discovery_fixture.checkout,
        discovery_fixture.context,
    )
    discovered.paths.environment.parent.mkdir(parents=True)
    original = (
        "# operator comment\n"
        "UNKNOWN_SETTING=preserve-me\n"
        "OCINT_DAEMON_API_TOKEN=existing-api\n"
        "OCINT_DAEMON_GITHUB_TOKEN=stale-github\n"
        "OCINT_DAEMON_SLACK_BOT_TOKEN=xoxb-existing\n"
        "OCINT_DAEMON_SLACK_SIGNING_SECRET=existing-signing-secret\n"
        "OCINT_NGROK_URL=https://static.example.test\n"
    )
    discovered.paths.environment.write_text(original)
    discovered.paths.environment.chmod(0o600)

    # WHEN
    setup(discovered, discovery_fixture.lifecycle)

    # THEN
    assert discovered.paths.environment.read_text() == original.replace("stale-github", "github-secret")
    assert stat.S_IMODE(discovered.paths.environment.stat().st_mode) == 0o600


def test_configured_coordinator_provisioning_is_idempotent_and_preserves_state_and_credentials(
    discovery_fixture: DiscoveryFixture,
) -> None:
    # GIVEN
    discovered = discover(
        discovery_fixture.runner,
        discovery_fixture.lifecycle,
        discovery_fixture.checkout,
        discovery_fixture.context,
    )
    setup(discovered, discovery_fixture.lifecycle)
    config = discovery_fixture.context.config()
    state = config.coordinator.opencode.xdg_data_home / "opencode" / "preserved-state"
    state.write_text("preserved")
    auth_before = discovered.opencode.auth_source.read_bytes()
    config_before = discovery_fixture.context.config_path.read_bytes()
    config.coordinator.opencode.config_file.unlink()

    # WHEN
    provision_configured_coordinator_runtime(discovery_fixture.context, config)
    provision_configured_coordinator_runtime(discovery_fixture.context, config)

    # THEN
    validate_coordinator_runtime(discovery_fixture.context, config)
    assert state.read_text() == "preserved"
    assert discovered.opencode.auth_source.read_bytes() == auth_before
    assert discovery_fixture.context.config_path.read_bytes() == config_before


def test_coordinator_runtime_validation_fails_closed_on_policy_drift(discovery_fixture: DiscoveryFixture) -> None:
    # GIVEN
    discovered = discover(
        discovery_fixture.runner,
        discovery_fixture.lifecycle,
        discovery_fixture.checkout,
        discovery_fixture.context,
    )
    setup(discovered, discovery_fixture.lifecycle)
    config = discovery_fixture.context.config()
    payload = config.coordinator.opencode.config_file.read_text().replace('"bash": "deny"', '"bash": "allow"')
    config.coordinator.opencode.config_file.write_text(payload)
    config.coordinator.opencode.config_file.chmod(0o600)

    # WHEN / THEN
    with pytest.raises(RuntimeError, match="does not exactly match"):
        validate_coordinator_runtime(discovery_fixture.context, config)


def test_setup_refuses_to_overwrite_existing_configuration(
    discovery_fixture: DiscoveryFixture,
) -> None:
    # GIVEN
    initial = discover(
        discovery_fixture.runner,
        discovery_fixture.lifecycle,
        discovery_fixture.checkout,
        discovery_fixture.context,
    )
    discovery_fixture.context.config_path.parent.mkdir()
    discovery_fixture.context.config_path.write_text(
        daemon_toml(
            discovered_daemon_config(
                initial,
                (
                    LifecycleConfig(startup_delay_seconds=75, inactive_interval_seconds=901),
                    LoggingConfig(max_bytes=2048, backup_count=2),
                ),
            )
        )
    )
    discovery_fixture.context.config_path.chmod(0o600)
    discovered = discover(
        discovery_fixture.runner,
        discovery_fixture.lifecycle,
        discovery_fixture.checkout,
        discovery_fixture.context,
    )

    original = discovery_fixture.context.config_path.read_bytes()

    # WHEN / THEN
    with pytest.raises(click.ClickException, match="will not be overwritten"):
        setup(discovered, discovery_fixture.lifecycle)
    assert discovery_fixture.context.config_path.read_bytes() == original


def test_discovery_fails_before_writes_when_git_remote_does_not_match_gh(
    discovery_fixture: DiscoveryFixture,
) -> None:
    # GIVEN
    discovery_fixture.runner.repository = "example-org/other-project"

    # WHEN / THEN
    with pytest.raises(click.ClickException, match="does not match"):
        discover(
            discovery_fixture.runner,
            discovery_fixture.lifecycle,
            discovery_fixture.checkout,
            discovery_fixture.context,
        )
    assert not discovery_fixture.managed_config.exists()


def test_discovery_rejects_ambiguous_effective_ssh_identities(discovery_fixture: DiscoveryFixture) -> None:
    # GIVEN
    second = discovery_fixture.home / ".ssh" / "second-key"
    second.write_text("private-key")
    second.chmod(0o600)
    discovery_fixture.runner.identities = (*discovery_fixture.runner.identities, second)

    # WHEN / THEN
    with pytest.raises(click.ClickException, match="exactly one"):
        discover(
            discovery_fixture.runner,
            discovery_fixture.lifecycle,
            discovery_fixture.checkout,
            discovery_fixture.context,
        )
    assert not discovery_fixture.managed_config.exists()


def test_restricted_opencode_config_keeps_only_selected_provider_model(tmp_path: Path) -> None:
    # GIVEN
    source = tmp_path / "opencode.json"
    source.write_text(
        """{
  "model": "example-provider/example-model",
  "instructions": ["global-rules.md"],
  "plugin": ["global-plugin"],
  "agent": {"build": {"prompt": "global-agent", "options": {"serviceTier": "priority", "unsafe": "drop"}}},
  "provider": {
    "example-provider": {
      "options": {"baseURL": "https://example.test/openai/v1", "apiKey": "must-not-copy"},
      "models": {
        "example-model": {
          "id": "example-model",
          "name": "example-model",
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
    selected = OpenCodeSourceConfig.model_validate_json(source.read_text())
    policy, _payload = load_policy()
    rendered = restricted_opencode_config(
        policy,
        selected.model,
        "example-provider",
        selected.provider["example-provider"],
        tmp_path / "worktrees",
        selected.agent.build.options.service_tier,
    )
    restricted = RestrictedOpenCodeConfig.model_validate_json(rendered)

    # THEN
    assert restricted.model == "example-provider/example-model"
    assert set(restricted.provider) == {"example-provider"}
    assert set(restricted.provider["example-provider"].models) == {"example-model"}
    assert restricted.provider["example-provider"].options.base_url == "https://example.test/openai/v1"
    assert restricted.instructions == []
    assert restricted.plugin == []
    assert restricted.agent.build is not None
    assert restricted.agent.build.options.service_tier == "priority"
    assert "must-not-copy" not in rendered
    assert "global-rules" not in rendered
    assert "global-plugin" not in rendered
    assert "global-agent" not in rendered
    assert "unsafe" not in rendered


def test_packaged_policy_is_the_authoritative_source_and_composition_preserves_it(tmp_path: Path) -> None:
    # GIVEN
    source_policy = Path(__file__).parents[5] / "config" / "opencode.daemon.json"
    source = tmp_path / "opencode.json"
    source.write_text(
        '{"model":"example-provider/example-model","provider":{"example-provider":'
        '{"options":{"baseURL":"https://example.test/v1","apiKey":"secret"},'
        '"models":{"example-model":{"id":"example-model","name":"Example"}}}}}'
    )

    # WHEN
    policy, packaged = load_policy()
    selected = OpenCodeSourceConfig.model_validate_json(source.read_text())
    effective = RestrictedOpenCodeConfig.model_validate_json(
        restricted_opencode_config(
            policy,
            selected.model,
            "example-provider",
            selected.provider["example-provider"],
            tmp_path / "managed-worktrees",
        )
    )

    # THEN
    assert packaged == policy_bytes() == source_policy.read_bytes()
    assert effective.share == policy.share
    assert effective.permission.fallback == "deny"
    assert effective.permission.bash == "allow"
    assert effective.permission.webfetch == "allow"
    assert effective.permission.websearch == "allow"
    assert effective.permission.question == "deny"
    assert effective.permission.external_directory == {
        "*": "deny",
        "/tmp/**": "allow",
        f"{(tmp_path / 'managed-worktrees').resolve()}/**": "allow",
    }
    assert "apiKey" not in effective.model_dump_json(by_alias=True)


def test_packaged_coordinator_policy_is_distinct_restricted_and_composed_without_source_tree(tmp_path: Path) -> None:
    # GIVEN
    source = OpenCodeSourceConfig.model_validate_json(
        '{"model":"example-provider/example-model","provider":{"example-provider":'
        '{"options":{"baseURL":"https://example.test/v1"},'
        '"models":{"example-model":{"id":"example-model","name":"Example"}}}}}'
    )

    # WHEN
    policy, packaged = load_coordinator_policy()
    rendered = coordinator_restricted_opencode_config(
        policy,
        source.model,
        "example-provider",
        source.provider["example-provider"],
    )
    effective = CoordinatorRestrictedOpenCodeConfig.model_validate_json(rendered)

    # THEN
    assert packaged == coordinator_policy_bytes()
    assert effective.model == "example-provider/example-model"
    assert effective.share == "disabled"
    assert effective.plugin == []
    assert effective.mcp == {}
    assert effective.lsp is False
    assert effective.permission.read == "allow"
    assert effective.permission.webfetch == "allow"
    assert effective.permission.websearch == "allow"
    assert effective.permission.edit == "deny"
    assert effective.permission.write == "deny"
    assert effective.permission.patch == "deny"
    assert effective.permission.bash == "deny"
    assert effective.permission.shell == "deny"
    assert effective.permission.question == "deny"
    assert effective.permission.external_directory == {"*": "deny"}
    assert str(tmp_path) not in rendered


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


def test_environment_upsert_preserves_comments_unknown_assignments_and_line_order(tmp_path: Path) -> None:
    # GIVEN
    destination = tmp_path / "daemon.env"
    write_private_file(destination, "# keep this\nOTHER=value\nOCINT_DAEMON_API_TOKEN=old\n\n")

    # WHEN
    upsert_private_environment(
        destination,
        {
            "OCINT_DAEMON_API_TOKEN": "new",
            "OCINT_DAEMON_SLACK_BOT_TOKEN": "xoxb-secret",
        },
    )

    # THEN
    assert destination.read_text() == (
        "# keep this\nOTHER=value\nOCINT_DAEMON_API_TOKEN=new\n\nOCINT_DAEMON_SLACK_BOT_TOKEN=xoxb-secret\n"
    )
    assert stat.S_IMODE(destination.stat().st_mode) == 0o600


def test_github_token_lookup_never_refreshes_authentication() -> None:
    # GIVEN
    runner = TokenRunner()

    # WHEN
    token = existing_github_token(runner, {"PATH": "/usr/bin"})

    # THEN
    assert token == "existing-token"
    assert runner.calls == [["gh", "auth", "token", "--hostname", "github.com"]]
    assert runner.environments == [{"PATH": "/usr/bin"}]
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
