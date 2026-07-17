import ast
from pathlib import Path


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
    assert not any(module.startswith("ocint.daemon.") and module != "ocint.daemon.config" for module in service_imports)


def test_prohibited_legacy_daemon_modules_are_absent() -> None:
    # GIVEN
    daemon = Path(__file__).parents[2] / "ocint" / "daemon"
    prohibited = {"models.py", "run.py", "runtime.py", "composition.py"}

    # WHEN
    existing = {path.name for path in daemon.glob("*.py")}

    # THEN
    assert existing.isdisjoint(prohibited)
