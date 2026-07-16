import ast
import json
from pathlib import Path


def test_daemon_opencode_policy_explicitly_denies_shell_and_network_publication() -> None:
    # GIVEN the tracked OpenCode daemon policy
    root = Path(__file__).parents[2]
    policy = json.loads((root / "config" / "opencode.daemon.json").read_text())

    # WHEN effective permissions are inspected
    permissions = policy["permission"]

    # THEN no shell approval path or publishing network tool is available
    assert permissions["bash"] == "deny"
    assert permissions["webfetch"] == "deny"
    assert permissions["websearch"] == "deny"
    assert "allow" not in json.dumps(permissions["bash"])


def test_execution_unit_has_no_control_publication_credentials() -> None:
    # GIVEN separate tracked execution and control units
    root = Path(__file__).parents[2]
    execution = (root / "systemd" / "ocint-opencode.service").read_text()
    control = (root / "systemd" / "ocint-daemon.service").read_text()

    # WHEN identities and credential directives are compared
    # THEN only the control identity receives provider credentials and both share only the worktree group
    assert "User=ocint-agent" in execution
    assert "User=ocint-control" in control
    assert "Group=ocint-agent" in execution
    assert "Group=ocint-control" in control
    assert "SupplementaryGroups=ocint-shared" in execution
    assert "SupplementaryGroups=ocint-shared" in control
    assert "github-token" not in execution
    assert "slack-token" not in execution
    assert "LoadCredential=github-token" in control
    assert "StateDirectory=ocint-control ocint-control/home" in control
    assert "StateDirectory=ocint-agent" in execution
    tmpfiles = (root / "systemd" / "ocint.conf").read_text()
    assert "/var/lib/ocint-worktrees 0770 ocint-agent ocint-shared" in tmpfiles
    assert "LoadCredential=git-config" in control
    assert "LoadCredential=git-push-credential" in control
    assert "git-push-credential" not in execution


def test_daemon_production_code_has_no_any_or_object_annotations() -> None:
    # GIVEN the daemon production package
    root = Path(__file__).parents[2] / "ocint" / "daemon"
    offenders: list[str] = []

    # WHEN annotation names are inspected
    for path in root.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Name) and node.id in {"Any", "object"}:
                offenders.append(str(path.relative_to(root)))

    # THEN concrete boundary types are used throughout
    assert offenders == []


def test_permission_events_abort_without_auto_approval_and_validation_has_no_secrets() -> None:
    # GIVEN the execution workflow and its explicit validation environment
    root = Path(__file__).parents[2] / "ocint" / "daemon"
    workflow = (root / "run.py").read_text()
    composition = (root / "composition.py").read_text()

    # WHEN permission and validation boundaries are inspected
    # THEN permission requests abort and repository checks receive no control/publication credential
    assert 'item.event_type.startswith("permission")' in workflow
    assert "await self.runtime.cancel" in workflow
    assert 'raise PermissionError("OpenCode requested an unapproved permission")' in workflow
    validation_line = next(line for line in composition.splitlines() if "validation_environment =" in line)
    assert "TOKEN" not in validation_line
    assert "HOME" not in validation_line
    assert "CREDENTIAL" not in validation_line
