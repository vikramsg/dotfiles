import json
import shutil
import sqlite3
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

import pytest
from click.testing import CliRunner
from ocint.cli import main
from ocint.daemon.config import DaemonContext, DaemonSettings
from ocint.daemon.coordinator.config import (
    CoordinatorWorkspaceConfig,
    RepositoryCatalogueEntry,
)
from ocint.daemon.coordinator.workspace import CoordinatorWorkspace
from ocint.daemon.db import current_daemon_head_revision, migrate_daemon_db
from ocint.daemon.lch.doctor import Diagnostic, DoctorReport, diagnose
from ocint.daemon.lch.opencode import (
    OpenCodeSourceConfig,
    coordinator_restricted_opencode_config,
    load_coordinator_policy,
    load_policy,
    restricted_opencode_config,
)
from ocint.daemon.lch.systemd import (
    CommandResult,
    NgrokRuntime,
    SystemdLifecycle,
    SystemdPaths,
    coordinator_ngrok_service_text,
    coordinator_service_text,
    service_text,
    timer_text,
)
from ocint.daemon.slack import CoordinatorSlackConfig
from ocint.presentation import default_cli_context


@dataclass
class DoctorRunner:
    opencode: Path
    fail_commands: bool = False
    isolated_calls: list[tuple[tuple[str, ...], Mapping[str, str]]] = field(default_factory=list)

    def run(self, arguments: Sequence[str]) -> CommandResult:
        command = tuple(arguments)
        if self.fail_commands:
            raise subprocess.CalledProcessError(2, command, stderr="service unavailable")
        if command[0] == "systemctl" and "list-timers" in command:
            return CommandResult(
                stdout='[{"next":1784312702000000,"last":1784311708000000,'
                '"unit":"ocint-daemon.timer","activates":"ocint-daemon.service"}]'
            )
        if command[0] == "systemctl" and any("ActiveState" in item for item in command):
            return CommandResult(stdout="active\n")
        if command[0] == "systemctl":
            return CommandResult(stdout="Fri 2026-07-17 12:00:00 UTC\n")
        if command[0] == "loginctl":
            return CommandResult(stdout="yes\n")
        if command[-1] == "version" and Path(command[0]).name == "ngrok":
            return CommandResult(stdout="ngrok version 3.31.0\n")
        raise AssertionError(command)

    def run_isolated(self, arguments: Sequence[str], environment: Mapping[str, str]) -> CommandResult:
        command = tuple(arguments)
        self.isolated_calls.append((command, environment))
        if self.fail_commands:
            raise subprocess.CalledProcessError(2, command, stderr="command unavailable")
        if command == (str(self.opencode), "--version"):
            return CommandResult(stdout="1.18.16\n")
        if command == ("gh", "api", "--hostname", "github.com", "user"):
            return CommandResult(stdout='{"login":"maintainer"}\n')
        if command == (
            "gh",
            "repo",
            "view",
            "example-org/project",
            "--json",
            "nameWithOwner,defaultBranchRef",
        ):
            return CommandResult(stdout='{"nameWithOwner":"example-org/project","defaultBranchRef":{"name":"main"}}\n')
        if command == ("gh", "auth", "token", "--hostname", "github.com"):
            return CommandResult(stdout="recognizable-gh-token\n")
        raise AssertionError(command)

    def run_interactive(self, arguments: Sequence[str], environment: Mapping[str, str]) -> None:
        _ = (arguments, environment)
        raise AssertionError("not used")


@dataclass
class DoctorFixture:
    home: Path
    config: Path
    environment: Path
    effective: Path
    coordinator_effective: Path
    source_config: Path
    auth_source: Path
    identity: Path
    known_hosts: Path
    database: Path
    runner: DoctorRunner
    lifecycle: SystemdLifecycle
    context: DaemonContext


@pytest.fixture
def doctor_fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> DoctorFixture:
    # GIVEN
    home = tmp_path / "home"
    config_home = home / "config"
    data_home = home / "data"
    state_home = home / "state"
    binary_home = home / "bin"
    for directory in (config_home / "ocint", data_home / "ocint", state_home / "ocint", binary_home):
        directory.mkdir(parents=True)
    source_config = config_home / "opencode" / "opencode.json"
    source_config.parent.mkdir()
    source_config.write_text(
        '{"model":"example-provider/example-model","agent":{"build":{"options":{"serviceTier":"priority"}}},'
        '"provider":{"example-provider":'
        '{"models":{"example-model":{"id":"example-model","name":"Example"}}}}}'
    )
    source_config.chmod(0o600)
    selected = OpenCodeSourceConfig.model_validate_json(source_config.read_text())
    policy, _payload = load_policy()
    effective = config_home / "ocint" / "opencode-xdg" / "opencode" / "opencode.json"
    effective.parent.mkdir(parents=True)
    effective.write_text(
        restricted_opencode_config(
            policy,
            selected.model,
            "example-provider",
            selected.provider["example-provider"],
            data_home / "ocint" / "worktrees",
            selected.agent.build.options.service_tier,
        )
    )
    effective.chmod(0o600)
    effective.parents[1].chmod(0o700)
    coordinator_policy, _coordinator_payload = load_coordinator_policy()
    coordinator_effective = config_home / "ocint" / "coordinator-opencode-xdg" / "opencode" / "opencode.json"
    coordinator_effective.parent.mkdir(parents=True)
    coordinator_effective.write_text(
        coordinator_restricted_opencode_config(
            coordinator_policy,
            selected.model,
            "example-provider",
            selected.provider["example-provider"],
        )
    )
    coordinator_effective.chmod(0o600)
    coordinator_effective.parents[1].chmod(0o700)
    auth_source = data_home / "opencode" / "auth.json"
    auth_source.parent.mkdir()
    auth_source.write_text("recognizable-auth-secret")
    auth_source.chmod(0o600)
    auth_link = data_home / "ocint" / "opencode-data" / "opencode" / "auth.json"
    auth_link.parent.mkdir(parents=True)
    auth_link.symlink_to(auth_source)
    auth_link.parents[1].chmod(0o700)
    coordinator_auth_link = data_home / "ocint" / "coordinator-opencode-data" / "opencode" / "auth.json"
    coordinator_auth_link.parent.mkdir(parents=True)
    coordinator_auth_link.symlink_to(auth_source)
    coordinator_auth_link.parents[1].chmod(0o700)
    ssh_name = shutil.which("ssh")
    assert ssh_name is not None
    ssh = Path(ssh_name).resolve()
    opencode = binary_home / "opencode"
    ocint = binary_home / "ocint"
    ngrok = binary_home / "ngrok"
    for executable in (opencode, ocint, ngrok):
        executable.write_text("#!/bin/sh\nexit 0\n")
        executable.chmod(0o755)
    identity = home / "ssh" / "project-key"
    identity.parent.mkdir()
    identity.write_text("recognizable-key-secret")
    identity.chmod(0o600)
    known_hosts = identity.parent / "known_hosts"
    known_hosts.write_text("example.test host-key")
    database = state_home / "ocint" / "daemon.sqlite"
    migrate_daemon_db(database)
    database.chmod(0o600)
    for directory in (data_home / "ocint" / "mirrors", data_home / "ocint" / "worktrees"):
        directory.mkdir()
        directory.chmod(0o700)
    environment = config_home / "ocint" / "daemon.env"
    environment.write_text(
        "OCINT_DAEMON_API_TOKEN=recognizable-api-token\n"
        "OCINT_DAEMON_GITHUB_TOKEN=recognizable-github-token\n"
        "OCINT_DAEMON_SLACK_BOT_TOKEN=recognizable-slack-token\n"
        "OCINT_DAEMON_SLACK_SIGNING_SECRET=recognizable-signing-secret\n"
        "OCINT_NGROK_URL=https://static.example.test\n"
    )
    environment.chmod(0o600)
    config = config_home / "ocint" / "daemon.toml"
    config.write_text(
        f'''database_path = "{database}"
mirror_root = "{data_home / "ocint" / "mirrors"}"
worktree_root = "{data_home / "ocint" / "worktrees"}"
[[repositories]]
name = "project"
description = "Repository for coordinator diagnostics."
remote_url = "git@github.com:example-org/project.git"
github_repository = "example-org/project"
author_name = "Example Author"
author_email = "author@example.test"
actors = ["maintainer"]
[opencode]
expected_version = "1.18.16"
executable = "{opencode}"
config_file = "{effective}"
xdg_config_home = "{effective.parents[1]}"
xdg_data_home = "{data_home / "ocint" / "opencode-data"}"
[github]
agent_actor = "maintainer"
[coordinator]
workspace_root = "{data_home / "ocint" / "coordinator"}"
turn_timeout_seconds = 1800
shutdown_timeout_seconds = 30
orphan_retention_seconds = 86400
retry_seconds = 5
response_chunk_characters = 3500
slack_post_interval_seconds = 1
[coordinator.ingress]
host = "127.0.0.1"
port = 8733
max_request_bytes = 65536
timestamp_tolerance_seconds = 300
[coordinator.slack]
workspace_id = "T-test"
[[coordinator.slack.channels]]
channel_id = "C-test"
authorized_users = ["U-test"]
[coordinator.opencode]
server_url = "http://127.0.0.1:4098"
expected_version = "1.18.16"
executable = "{opencode}"
config_file = "{coordinator_effective}"
xdg_config_home = "{coordinator_effective.parents[1]}"
xdg_data_home = "{data_home / "ocint" / "coordinator-opencode-data"}"
[git]
ssh_executable = "{ssh}"
identity_file = "{identity}"
known_hosts_file = "{known_hosts}"
'''
    )
    config.chmod(0o600)
    CoordinatorWorkspace(
        CoordinatorWorkspaceConfig(
            root=data_home / "ocint" / "coordinator",
            repositories=(
                RepositoryCatalogueEntry(
                    name="project",
                    description="Repository for coordinator diagnostics.",
                    github_repository="example-org/project",
                    default_branch="main",
                ),
            ),
        )
    ).generate()
    paths = SystemdPaths(
        directory=config_home / "systemd" / "user",
        environment_file=environment,
        config_home=config_home,
        data_home=data_home,
        state_home=state_home,
        daemon_config=config,
        home=home,
        user="example-user",
    )
    context = DaemonContext.create(
        default_cli_context().output,
        home,
        {
            "XDG_CONFIG_HOME": str(config_home),
            "XDG_DATA_HOME": str(data_home),
            "XDG_STATE_HOME": str(state_home),
            "PATH": f"{binary_home}:/usr/bin:/bin",
            "USER": "example-user",
        },
        DaemonSettings(config=config),
    )
    paths.directory.mkdir(parents=True)
    paths.service.write_text(
        service_text(
            ocint,
            paths.environment_reference,
            paths.reference(config_home),
            paths.reference(data_home),
            paths.reference(state_home),
            paths.reference(config),
        )
    )
    paths.timer.write_text(timer_text(context.config().lifecycle))
    paths.coordinator_service.write_text(
        coordinator_service_text(
            ocint,
            paths.environment_reference,
            paths.reference(config_home),
            paths.reference(data_home),
            paths.reference(state_home),
            paths.reference(config),
        )
    )
    paths.coordinator_ngrok_service.write_text(
        coordinator_ngrok_service_text(
            NgrokRuntime(
                executable=ngrok.resolve(),
                version="ngrok version 3.31.0",
                url="https://static.example.test",
            ),
            paths.reference(home),
            paths.reference(config_home),
            "C.UTF-8",
            8733,
        )
    )
    paths.service.chmod(0o644)
    paths.timer.chmod(0o644)
    paths.coordinator_service.chmod(0o644)
    paths.coordinator_ngrok_service.chmod(0o644)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(config_home))
    monkeypatch.setenv("XDG_DATA_HOME", str(data_home))
    monkeypatch.setenv("XDG_STATE_HOME", str(state_home))
    monkeypatch.setenv("PATH", f"{binary_home}:/usr/bin:/bin")
    monkeypatch.setenv("USER", "example-user")
    runner = DoctorRunner(opencode)
    lifecycle = SystemdLifecycle(paths, runner)

    async def check_slack_access(_config: CoordinatorSlackConfig, token: str) -> str:
        assert token == "recognizable-slack-token"
        return "workspace=T-test; channels=1; scopes=channels:history,chat:write"

    monkeypatch.setattr("ocint.daemon.lch.doctor.check_slack_access", check_slack_access)
    return DoctorFixture(
        home,
        config,
        environment,
        effective,
        coordinator_effective,
        source_config,
        auth_source,
        identity,
        known_hosts,
        database,
        runner,
        lifecycle,
        context,
    )


def test_diagnose_reports_healthy_complete_configuration(doctor_fixture: DoctorFixture) -> None:
    # GIVEN / WHEN
    report = diagnose(doctor_fixture.context, doctor_fixture.runner, doctor_fixture.lifecycle)

    # THEN
    assert report.healthy, [(item.name, item.detail) for item in report.diagnostics if item.required and not item.ok]
    assert len(report.diagnostics) >= 25
    assert all(item.ok for item in report.diagnostics if item.required)
    packaged = next(item for item in report.diagnostics if item.name == "opencode.packaged_policy")
    schedule = next(item for item in report.diagnostics if item.name == "systemd.schedule")
    coordinator_policy = next(
        item for item in report.diagnostics if item.name == "coordinator.opencode.packaged_policy"
    )
    workspace = next(item for item in report.diagnostics if item.name == "coordinator.workspace")
    ports = next(item for item in report.diagnostics if item.name == "ports.distinct_loopback")
    ngrok = next(item for item in report.diagnostics if item.name == "ngrok.executable_version")
    assert "resource=" in packaged.detail
    assert '"*":"deny"' in packaged.value
    assert '"bash":"allow"' in packaged.value
    assert '"webfetch":"allow"' in packaged.value
    assert '"websearch":"allow"' in packaged.value
    assert '"question":"deny"' in packaged.value
    assert schedule.ok
    assert "next=2026-07-17T18:25:02Z" in schedule.value
    assert coordinator_policy.ok
    assert '"bash":"deny"' in coordinator_policy.value
    assert workspace.ok
    assert "catalogue_exact=True" in workspace.detail
    assert ports.ok
    assert all(str(port) in ports.value for port in (8732, 8733, 4097, 4098))
    assert ngrok.ok
    assert "ngrok version 3.31.0" in ngrok.value


def test_diagnose_rejects_unsafe_ngrok_url_without_exposing_it(doctor_fixture: DoctorFixture) -> None:
    # GIVEN
    doctor_fixture.environment.write_text(
        doctor_fixture.environment.read_text().replace(
            "https://static.example.test",
            "https://user@static.example.test/events?token=recognizable-ngrok-secret",
        )
    )

    # WHEN
    report = diagnose(doctor_fixture.context, doctor_fixture.runner, doctor_fixture.lifecycle)

    # THEN
    url = next(item for item in report.diagnostics if item.name == "ngrok.url")
    unit = next(item for item in report.diagnostics if item.name == "systemd.coordinator_ngrok_service")
    assert not url.ok
    assert not unit.ok
    assert "recognizable-ngrok-secret" not in report.human_text()


def test_diagnose_accepts_validated_source_config_and_readable_known_hosts_symlinks(
    doctor_fixture: DoctorFixture,
) -> None:
    # GIVEN
    source_target = doctor_fixture.source_config.with_name("source-target.json")
    source_target.write_text(doctor_fixture.source_config.read_text())
    source_target.chmod(0o644)
    doctor_fixture.source_config.unlink()
    doctor_fixture.source_config.symlink_to(source_target)
    known_target = doctor_fixture.known_hosts.with_name("known-hosts-target")
    known_target.write_text(doctor_fixture.known_hosts.read_text())
    doctor_fixture.known_hosts.unlink()
    doctor_fixture.known_hosts.symlink_to(known_target)

    # WHEN
    report = diagnose(doctor_fixture.context, doctor_fixture.runner, doctor_fixture.lifecycle)

    # THEN
    assert report.healthy
    git = next(item for item in report.diagnostics if item.name == "git.remote_author_ssh")
    effective = next(item for item in report.diagnostics if item.name == "opencode.effective_config")
    paths = next(item for item in report.diagnostics if item.name == "opencode.config_paths")
    assert git.ok
    assert "/ssh" in git.value
    assert effective.ok
    assert paths.ok
    assert f"source={doctor_fixture.source_config}" in paths.value
    assert f"link={doctor_fixture.source_config}" in paths.value
    assert f"target={source_target}" in paths.value


def test_diagnose_accepts_runtime_owned_workspace_files_before_coordinator_rollout(
    doctor_fixture: DoctorFixture,
) -> None:
    # GIVEN
    workspace = doctor_fixture.context.config().coordinator.workspace_root
    (workspace / "AGENTS.md").unlink()
    (workspace / "repositories.json").unlink()

    # WHEN
    report = diagnose(doctor_fixture.context, doctor_fixture.runner, doctor_fixture.lifecycle)

    # THEN
    diagnostic = next(item for item in report.diagnostics if item.name == "coordinator.workspace")
    assert report.healthy
    assert diagnostic.ok
    assert "runtime_owned_pending=True" in diagnostic.detail


def test_diagnose_renders_invalid_toml_before_failing(doctor_fixture: DoctorFixture) -> None:
    # GIVEN
    doctor_fixture.config.write_text("not = [valid")
    doctor_fixture.config.chmod(0o600)

    # WHEN
    context = DaemonContext.create(
        doctor_fixture.context.output,
        doctor_fixture.home,
        doctor_fixture.context.environment,
        doctor_fixture.context.settings,
    )
    report = diagnose(context, doctor_fixture.runner, doctor_fixture.lifecycle)

    # THEN
    assert not report.healthy
    assert len(report.diagnostics) >= 20
    effective = next(item for item in report.diagnostics if item.name == "config.effective")
    assert not effective.ok
    assert effective.detail


def test_diagnose_rejects_unsafe_managed_files(doctor_fixture: DoctorFixture) -> None:
    # GIVEN
    doctor_fixture.environment.chmod(0o644)
    doctor_fixture.effective.chmod(0o644)
    doctor_fixture.auth_source.chmod(0o644)
    doctor_fixture.identity.chmod(0o644)

    # WHEN
    report = diagnose(doctor_fixture.context, doctor_fixture.runner, doctor_fixture.lifecycle)

    # THEN
    assert not report.healthy
    failed = {item.name for item in report.diagnostics if item.required and not item.ok}
    assert {"env.path", "opencode.effective_config", "opencode.auth", "git.remote_author_ssh"}.issubset(failed)


def test_diagnose_rejects_effective_service_tier_drift(doctor_fixture: DoctorFixture) -> None:
    # GIVEN
    effective = json.loads(doctor_fixture.effective.read_text())
    effective["agent"]["build"]["options"]["serviceTier"] = "standard"
    doctor_fixture.effective.write_text(json.dumps(effective))

    # WHEN
    report = diagnose(doctor_fixture.context, doctor_fixture.runner, doctor_fixture.lifecycle)

    # THEN
    diagnostic = next(item for item in report.diagnostics if item.name == "opencode.effective_config")
    assert not diagnostic.ok
    assert "policy_preserved=False" in diagnostic.detail


def test_diagnose_rejects_extra_effective_agent_policy(doctor_fixture: DoctorFixture) -> None:
    # GIVEN
    effective = json.loads(doctor_fixture.effective.read_text())
    effective["agent"]["build"]["prompt"] = "unmanaged prompt"
    doctor_fixture.effective.write_text(json.dumps(effective))

    # WHEN
    report = diagnose(doctor_fixture.context, doctor_fixture.runner, doctor_fixture.lifecycle)

    # THEN
    diagnostic = next(item for item in report.diagnostics if item.name == "opencode.effective_config")
    assert not diagnostic.ok
    assert diagnostic.detail


def test_diagnose_reports_missing_managed_files(doctor_fixture: DoctorFixture) -> None:
    # GIVEN
    doctor_fixture.environment.unlink()
    doctor_fixture.auth_source.unlink()

    # WHEN
    report = diagnose(doctor_fixture.context, doctor_fixture.runner, doctor_fixture.lifecycle)

    # THEN
    failed = {item.name for item in report.diagnostics if item.required and not item.ok}
    assert {"env.path", "env.OCINT_DAEMON_API_TOKEN", "env.OCINT_DAEMON_GITHUB_TOKEN", "opencode.auth"}.issubset(failed)


def test_diagnose_rejects_nonexact_or_unsafe_systemd_units(doctor_fixture: DoctorFixture) -> None:
    # GIVEN
    doctor_fixture.lifecycle.paths.service.write_text("[Service]\nExecStart=/wrong\n")
    doctor_fixture.lifecycle.paths.timer.chmod(0o600)
    doctor_fixture.lifecycle.paths.coordinator_service.write_text("[Service]\nExecStart=/wrong\n")
    doctor_fixture.lifecycle.paths.coordinator_ngrok_service.write_text("[Service]\nExecStart=/wrong\n")

    # WHEN
    report = diagnose(doctor_fixture.context, doctor_fixture.runner, doctor_fixture.lifecycle)

    # THEN
    service = next(item for item in report.diagnostics if item.name == "systemd.service")
    timer = next(item for item in report.diagnostics if item.name == "systemd.timer")
    coordinator = next(item for item in report.diagnostics if item.name == "systemd.coordinator_service")
    ngrok = next(item for item in report.diagnostics if item.name == "systemd.coordinator_ngrok_service")
    assert not service.ok
    assert "payload_exact=False" in service.detail
    assert not timer.ok
    assert "mode=0600" in timer.detail
    assert not coordinator.ok
    assert "payload_exact=False" in coordinator.detail
    assert not ngrok.ok
    assert "payload_exact=False" in ngrok.detail


def test_diagnose_requires_coordinator_ingress_credentials_without_exposing_values(
    doctor_fixture: DoctorFixture,
) -> None:
    # GIVEN
    doctor_fixture.environment.write_text(
        "OCINT_DAEMON_API_TOKEN=recognizable-api-token\n"
        "OCINT_DAEMON_GITHUB_TOKEN=recognizable-github-token\n"
        "OCINT_DAEMON_SLACK_BOT_TOKEN=recognizable-slack-token\n"
    )

    # WHEN
    report = diagnose(doctor_fixture.context, doctor_fixture.runner, doctor_fixture.lifecycle)

    # THEN
    signing = next(item for item in report.diagnostics if item.name == "env.OCINT_DAEMON_SLACK_SIGNING_SECRET")
    ngrok = next(item for item in report.diagnostics if item.name == "env.OCINT_NGROK_URL")
    assert not signing.ok
    assert signing.value == "missing"
    assert not ngrok.ok
    assert ngrok.value == "missing"
    assert "recognizable" not in signing.value + signing.detail + ngrok.value + ngrok.detail


def test_diagnose_preserves_actionable_command_failures(doctor_fixture: DoctorFixture) -> None:
    # GIVEN
    doctor_fixture.runner.fail_commands = True

    # WHEN
    report = diagnose(doctor_fixture.context, doctor_fixture.runner, doctor_fixture.lifecycle)

    # THEN
    assert not report.healthy
    login = next(item for item in report.diagnostics if item.name == "github.login")
    state = next(item for item in report.diagnostics if item.name == "systemd.state")
    assert "command failed" in login.detail
    assert "command failed" in state.detail


def test_diagnose_reports_pending_startup_migration_without_writing_database(doctor_fixture: DoctorFixture) -> None:
    # GIVEN
    with sqlite3.connect(doctor_fixture.database) as connection:
        connection.execute("UPDATE alembic_version SET version_num = ?", ("outdated_revision",))

    # WHEN
    report = diagnose(doctor_fixture.context, doctor_fixture.runner, doctor_fixture.lifecycle)

    # THEN
    migration = next(item for item in report.diagnostics if item.name == "database.migration")
    assert report.healthy
    assert not migration.ok
    assert not migration.required
    assert migration.value == "outdated_revision"
    assert migration.detail == (f"head={current_daemon_head_revision()}; timer/coordinator startup owns migration")


def test_diagnose_human_json_parity_redacts_all_secret_material(doctor_fixture: DoctorFixture) -> None:
    # GIVEN
    effective_payload = json.loads(doctor_fixture.effective.read_text())
    effective_payload["provider"]["example-provider"]["options"] = {"apiKey": "recognizable-provider-secret"}
    doctor_fixture.effective.write_text(json.dumps(effective_payload))
    doctor_fixture.effective.chmod(0o600)

    # WHEN
    report = diagnose(doctor_fixture.context, doctor_fixture.runner, doctor_fixture.lifecycle)
    human = report.human_text()
    machine = report.json_text()
    decoded = json.loads(machine)

    # THEN
    assert decoded["healthy"] == report.healthy
    assert len(decoded["diagnostics"]) == len(report.diagnostics)
    for diagnostic in report.diagnostics:
        assert diagnostic.name in human
        assert diagnostic.name in machine
    for secret in (
        "recognizable-api-token",
        "recognizable-github-token",
        "recognizable-gh-token",
        "recognizable-auth-secret",
        "recognizable-key-secret",
        "recognizable-provider-secret",
        "recognizable-slack-token",
        "recognizable-signing-secret",
        "https://static.example.test",
    ):
        assert secret not in human
        assert secret not in machine


def test_doctor_cli_renders_complete_report_then_exits_nonzero(monkeypatch: pytest.MonkeyPatch) -> None:
    # GIVEN
    report = DoctorReport(
        diagnostics=(
            Diagnostic(name="first", required=True, ok=True, value="ready"),
            Diagnostic(name="last", required=True, ok=False, value="missing", detail="fix this"),
        )
    )
    monkeypatch.setattr("ocint.daemon.cli.diagnose", lambda _home, _runner, _lifecycle: report)

    # WHEN
    result = CliRunner().invoke(main, ["daemon", "doctor"])

    # THEN
    assert result.exit_code == 1
    assert "first" in result.output
    assert "last" in result.output
    assert "fix this" in result.output
