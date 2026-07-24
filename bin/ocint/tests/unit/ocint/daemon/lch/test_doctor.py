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
from ocint.daemon.db import current_daemon_head_revision, migrate_daemon_db
from ocint.daemon.lch.doctor import Diagnostic, DoctorReport, diagnose
from ocint.daemon.lch.provision import OpenCodeSourceConfig, load_policy, restricted_opencode_config
from ocint.daemon.lch.systemd import (
    CommandResult,
    SystemdLifecycle,
    SystemdPaths,
    service_text,
    timer_text,
)
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
        raise AssertionError(command)

    def run_isolated(self, arguments: Sequence[str], environment: Mapping[str, str]) -> CommandResult:
        command = tuple(arguments)
        self.isolated_calls.append((command, environment))
        if self.fail_commands:
            raise subprocess.CalledProcessError(2, command, stderr="command unavailable")
        if command == (str(self.opencode), "--version"):
            return CommandResult(stdout="1.17.20\n")
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
    auth_source = data_home / "opencode" / "auth.json"
    auth_source.parent.mkdir()
    auth_source.write_text("recognizable-auth-secret")
    auth_source.chmod(0o600)
    auth_link = data_home / "ocint" / "opencode-data" / "opencode" / "auth.json"
    auth_link.parent.mkdir(parents=True)
    auth_link.symlink_to(auth_source)
    auth_link.parents[1].chmod(0o700)
    ssh_name = shutil.which("ssh")
    assert ssh_name is not None
    ssh = Path(ssh_name).resolve()
    opencode = binary_home / "opencode"
    ocint = binary_home / "ocint"
    for executable in (opencode, ocint):
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
        "OCINT_DAEMON_API_TOKEN=recognizable-api-token\nOCINT_DAEMON_GITHUB_TOKEN=recognizable-github-token\n"
    )
    environment.chmod(0o600)
    config = config_home / "ocint" / "daemon.toml"
    config.write_text(
        f'''database_path = "{database}"
mirror_root = "{data_home / "ocint" / "mirrors"}"
worktree_root = "{data_home / "ocint" / "worktrees"}"
[[repositories]]
name = "project"
remote_url = "git@github.com:example-org/project.git"
github_repository = "example-org/project"
author_name = "Example Author"
author_email = "author@example.test"
actors = ["maintainer"]
[opencode]
expected_version = "1.17.20"
executable = "{opencode}"
config_file = "{effective}"
xdg_config_home = "{effective.parents[1]}"
xdg_data_home = "{data_home / "ocint" / "opencode-data"}"
[github]
agent_actor = "maintainer"
[git]
ssh_executable = "{ssh}"
identity_file = "{identity}"
known_hosts_file = "{known_hosts}"
'''
    )
    config.chmod(0o600)
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
    paths.service.chmod(0o644)
    paths.timer.chmod(0o644)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(config_home))
    monkeypatch.setenv("XDG_DATA_HOME", str(data_home))
    monkeypatch.setenv("XDG_STATE_HOME", str(state_home))
    monkeypatch.setenv("PATH", f"{binary_home}:/usr/bin:/bin")
    monkeypatch.setenv("USER", "example-user")
    runner = DoctorRunner(opencode)
    lifecycle = SystemdLifecycle(paths, runner)
    return DoctorFixture(
        home,
        config,
        environment,
        effective,
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
    assert "resource=" in packaged.detail
    assert '"*":"deny"' in packaged.value
    assert '"bash":"allow"' in packaged.value
    assert '"webfetch":"allow"' in packaged.value
    assert '"websearch":"allow"' in packaged.value
    assert '"question":"deny"' in packaged.value
    assert schedule.ok
    assert "next=2026-07-17T18:25:02Z" in schedule.value


def test_diagnose_accepts_system_ssh_and_readable_symlinked_discovery_files(
    doctor_fixture: DoctorFixture,
) -> None:
    # GIVEN
    source_target = doctor_fixture.source_config.with_name("source-target.json")
    source_target.write_text(doctor_fixture.source_config.read_text())
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
    paths = next(item for item in report.diagnostics if item.name == "opencode.config_paths")
    assert git.ok
    assert "/ssh" in git.value
    assert paths.ok


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

    # WHEN
    report = diagnose(doctor_fixture.context, doctor_fixture.runner, doctor_fixture.lifecycle)

    # THEN
    service = next(item for item in report.diagnostics if item.name == "systemd.service")
    timer = next(item for item in report.diagnostics if item.name == "systemd.timer")
    assert not service.ok
    assert "payload_exact=False" in service.detail
    assert not timer.ok
    assert "mode=0600" in timer.detail


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


def test_diagnose_reports_migration_failure_without_writing_database(doctor_fixture: DoctorFixture) -> None:
    # GIVEN
    with sqlite3.connect(doctor_fixture.database) as connection:
        connection.execute("UPDATE alembic_version SET version_num = ?", ("outdated_revision",))

    # WHEN
    report = diagnose(doctor_fixture.context, doctor_fixture.runner, doctor_fixture.lifecycle)

    # THEN
    migration = next(item for item in report.diagnostics if item.name == "database.migration")
    assert not migration.ok
    assert migration.value == "outdated_revision"
    assert migration.detail == f"head={current_daemon_head_revision()}"


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
