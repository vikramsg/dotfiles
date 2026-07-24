import ast
import json
import re
import subprocess
import sys
import tomllib
from pathlib import Path


def test_prohibited_legacy_daemon_modules_are_absent() -> None:
    # GIVEN
    daemon = Path(__file__).parents[2] / "ocint" / "daemon"
    prohibited = {"channels.py", "runtime.py", "composition.py"}

    # WHEN
    existing = {path.name for path in daemon.glob("*.py")}

    # THEN
    assert existing.isdisjoint(prohibited)

    package = daemon.parents[1]
    assert not (package / "systemd").exists()


def test_github_config_import_does_not_initialize_runtime_modules() -> None:
    # GIVEN
    package = Path(__file__).parents[2]
    script = """
import json
import sys
import ocint.daemon.github.config
names = [
    "ocint.daemon.github.client",
    "ocint.daemon.github.repository",
    "ocint.daemon.github.service",
    "ocint.daemon.github.integration",
    "ocint.daemon.github.runtime",
]
print(json.dumps([name for name in names if name in sys.modules]))
"""

    # WHEN
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=package,
        check=True,
        capture_output=True,
        text=True,
    )

    # THEN
    assert json.loads(result.stdout) == []


def test_github_facade_exports_only_supported_api() -> None:
    # GIVEN / WHEN
    import ocint.daemon.github as github_api

    # THEN
    assert github_api.__all__ == [
        "GitHubConfig",
        "GitHubGateway",
        "GitHubRepositoryPolicies",
        "GitHubRepositoryPolicy",
        "open_github_service",
    ]
    github = Path(__file__).parents[2] / "ocint" / "daemon" / "github"
    assert not (github / "runtime.py").exists()
    assert not (github / "integration.py").exists()


def test_thread_core_contains_only_provider_neutral_identity_and_title() -> None:
    # GIVEN
    models = Path(__file__).parents[2] / "ocint" / "daemon" / "tasks" / "models.py"

    # WHEN
    tree = ast.parse(models.read_text())
    thread = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "Thread")
    fields = {
        node.target.id for node in thread.body if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name)
    }

    # THEN
    assert fields == {"id", "source_id", "configured_repository", "eligible", "title"}


def test_daemon_artifacts_use_structural_pii_free_provisioning_examples() -> None:
    # GIVEN
    package = Path(__file__).parents[2]
    paths = [
        *(package / "ocint" / "daemon").rglob("*.py"),
        package / "config" / "daemon.example.toml",
        package / "config" / "opencode.daemon.json",
        package / "docs" / "daemon.md",
        package / "docs" / "daemon" / "workflow.md",
    ]
    example = tomllib.loads((package / "config" / "daemon.example.toml").read_text())
    policy = json.loads((package / "config" / "opencode.daemon.json").read_text())
    config_tree = ast.parse((package / "ocint" / "daemon" / "config.py").read_text())

    # WHEN
    absolute_homes = [str(path) for path in paths if re.search(r"/home/[A-Za-z0-9._-]+", path.read_text())]
    agent_defaults = [
        node
        for node in ast.walk(config_tree)
        if isinstance(node, ast.AnnAssign)
        and isinstance(node.target, ast.Name)
        and node.target.id == "agent_actor"
        and node.value is not None
    ]

    # THEN
    assert absolute_homes == []
    assert example["repositories"][0]["github_repository"] == "OWNER/REPOSITORY"
    assert example["repositories"][0]["remote_url"] == "git@github.com:OWNER/REPOSITORY.git"
    assert agent_defaults == []
    assert "model" not in policy
    assert "provider" not in policy
    assert policy["permission"]["*"] == "deny"
    assert policy["permission"]["external_directory"] == {"*": "deny"}
    assert policy["permission"]["bash"] == "allow"
    assert policy["permission"]["webfetch"] == "allow"
    assert policy["permission"]["websearch"] == "allow"
    assert policy["permission"]["question"] == "deny"


def test_policy_resource_is_one_canonical_symlinked_source() -> None:
    # GIVEN
    package = Path(__file__).parents[2]
    resource = package / "ocint" / "daemon" / "opencode.daemon.json"
    source = package / "config" / "opencode.daemon.json"

    # WHEN / THEN
    assert resource.is_symlink()
    assert resource.resolve() == source.resolve()
    assert resource.read_bytes() == source.read_bytes()


def test_root_daemon_cli_uses_only_the_lch_facade() -> None:
    # GIVEN
    cli = Path(__file__).parents[2] / "ocint" / "daemon" / "cli.py"

    # WHEN
    tree = ast.parse(cli.read_text())
    lch_imports = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None and node.module.startswith("ocint.daemon.lch")
    }

    # THEN
    assert lch_imports == {"ocint.daemon.lch"}


def test_daemon_log_events_do_not_include_secret_or_prompt_fields() -> None:
    # GIVEN
    daemon = Path(__file__).parents[2] / "ocint" / "daemon"
    prohibited = {"body", "environment", "identity_file", "password", "prompt", "token"}

    # WHEN
    fields: set[str] = set()
    for module in daemon.rglob("*.py"):
        tree = ast.parse(module.read_text())
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "logger"
            ):
                fields.update(keyword.arg for keyword in node.keywords if keyword.arg is not None)

    # THEN
    assert fields.isdisjoint(prohibited)


def test_daemon_context_is_the_only_configuration_load_boundary() -> None:
    # GIVEN
    daemon = Path(__file__).parents[2] / "ocint" / "daemon"

    # WHEN
    tomllib_importers = []
    settings_constructors = []
    for module in daemon.rglob("*.py"):
        tree = ast.parse(module.read_text())
        if any(
            (isinstance(node, ast.Import) and any(alias.name == "tomllib" for alias in node.names))
            or (isinstance(node, ast.ImportFrom) and node.module == "tomllib")
            for node in ast.walk(tree)
        ):
            tomllib_importers.append(module.name)
        if any(
            isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "DaemonSettings"
            for node in ast.walk(tree)
        ):
            settings_constructors.append(module.name)

    # THEN
    assert tomllib_importers == ["config.py"]
    assert settings_constructors == ["config.py"]


def test_lch_receives_policy_without_owning_defaults() -> None:
    # GIVEN
    daemon = Path(__file__).parents[2] / "ocint" / "daemon"
    systemd = (daemon / "lch" / "systemd.py").read_text()
    logging = (daemon / "logging.py").read_text()

    # THEN
    assert "OnStartupSec=1m" not in systemd
    assert "OnUnitInactiveSec=15m" not in systemd
    assert "default=10 * 1024 * 1024" not in logging
    assert "default=5" not in logging
