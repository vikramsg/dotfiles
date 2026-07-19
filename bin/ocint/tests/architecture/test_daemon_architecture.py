import ast
import json
import re
import tomllib
from pathlib import Path


def test_daemon_has_only_intended_modules() -> None:
    daemon = Path(__file__).parents[2] / "ocint" / "daemon"

    assert {path.name for path in daemon.glob("*.py")} == {
        "__init__.py",
        "api.py",
        "cli.py",
        "config.py",
        "git.py",
        "logging.py",
        "models.py",
        "opencode.py",
        "repository.py",
        "run.py",
        "service.py",
    }


def test_daemon_core_does_not_import_frameworks_or_concrete_adapters() -> None:
    # GIVEN
    daemon = Path(__file__).parents[2] / "ocint" / "daemon"
    prohibited = {"aiohttp", "alembic", "fastapi", "httpx", "sqlite3", "sqlalchemy", "uvicorn"}

    # WHEN
    imported: set[str] = set()
    for module in (daemon / "config.py", daemon / "service.py"):
        tree = ast.parse(module.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module is not None:
                imported.add(node.module.split(".")[0])

    # THEN
    assert imported.isdisjoint(prohibited)


def test_daemon_core_import_direction_points_from_service_to_config() -> None:
    # GIVEN
    daemon = Path(__file__).parents[2] / "ocint" / "daemon"

    # WHEN
    config_tree = ast.parse((daemon / "config.py").read_text())
    service_tree = ast.parse((daemon / "service.py").read_text())
    config_imports = {
        node.module for node in ast.walk(config_tree) if isinstance(node, ast.ImportFrom) and node.module is not None
    }
    service_imports = {
        node.module for node in ast.walk(service_tree) if isinstance(node, ast.ImportFrom) and node.module is not None
    }

    # THEN
    assert not any(module.startswith("ocint.daemon") for module in config_imports)
    assert service_imports.intersection({"ocint.daemon.config"}) == {"ocint.daemon.config"}
    assert not any(
        module.startswith("ocint.daemon.") and module not in {"ocint.daemon.config", "ocint.daemon.logging"}
        for module in service_imports
    )


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


def test_daemon_logging_depends_on_the_log_rotation_contract() -> None:
    # GIVEN
    logging_module = Path(__file__).parents[2] / "ocint" / "daemon" / "logging.py"

    # WHEN
    tree = ast.parse(logging_module.read_text())
    imports = {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module is not None}

    # THEN
    assert "ocint.daemon.models" in imports
    assert "ocint.daemon.config" not in imports


def test_daemon_migrations_are_independent_of_live_metadata() -> None:
    # GIVEN
    versions = Path(__file__).parents[2] / "ocint" / "daemon" / "db" / "migrations" / "versions"

    # WHEN
    revisions = [path for path in versions.glob("*.py") if path.name != "__init__.py"]
    tree = ast.parse(revisions[0].read_text())
    imports = {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module is not None}

    # THEN
    assert {path.name for path in revisions} == {
        "20260716_create_daemon_control.py",
        "20260717_add_github_issues.py",
        "20260718_replace_github_workflow_with_threads.py",
        "20260719_add_thread_eligibility.py",
        "20260719_add_thread_execution_job.py",
    }
    assert "ocint.daemon.db.schema" not in imports


def test_production_uses_the_github_facade() -> None:
    # GIVEN
    daemon = Path(__file__).parents[2] / "ocint" / "daemon"
    private = {
        "ocint.daemon.github.client",
        "ocint.daemon.github.models",
        "ocint.daemon.github.repository",
        "ocint.daemon.github.service",
    }

    # WHEN
    imported: set[str] = set()
    for module in daemon.rglob("*.py"):
        if (daemon / "github") in module.parents:
            continue
        tree = ast.parse(module.read_text())
        imported.update(
            node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module is not None
        )

    # THEN
    assert imported.isdisjoint(private)
    assert not (daemon / "github.py").exists()


def test_task_core_is_provider_neutral() -> None:
    # GIVEN
    tasks = Path(__file__).parents[2] / "ocint" / "daemon" / "tasks"

    # WHEN
    imports = set()
    for module in tasks.glob("*.py"):
        tree = ast.parse(module.read_text())
        imports.update(
            node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module is not None
        )

    # THEN
    assert not any(module.startswith("ocint.daemon.github") for module in imports)


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
    assert policy["permission"]["external_directory"] == {"*": "deny"}


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
