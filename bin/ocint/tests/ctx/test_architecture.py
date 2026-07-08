import ast
from collections.abc import Iterator
from pathlib import Path

PACKAGE_ROOT = Path(__file__).parents[2] / "ocint"
CTX_ROOT = PACKAGE_ROOT / "ctx"


def iter_python_files(root: Path) -> Iterator[Path]:
    """FIXME: Move import-boundary enforcement into tooling once this repo has a dedicated architecture lint rule."""
    yield from root.rglob("*.py")


def test_no_relative_imports() -> None:
    offenders: list[str] = []
    for path in iter_python_files(PACKAGE_ROOT):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.ImportFrom) and node.level:
                offenders.append(str(path.relative_to(PACKAGE_ROOT)))

    assert offenders == []


def test_search_workflow_does_not_import_opencode() -> None:
    imports = _imports(CTX_ROOT / "search.py")

    assert not any(name.startswith("ocint.opencode") for name in imports)


def test_only_import_workflow_imports_opencode_repository() -> None:
    offenders = []
    for path in iter_python_files(CTX_ROOT):
        imported = _from_imports(path)
        if ("ocint.opencode.repository", "OpenCodeRepository") in imported:
            offenders.append(str(path.relative_to(CTX_ROOT)))

    assert offenders == ["importer.py"]


def test_workflows_do_not_own_db_lifecycle() -> None:
    workflow_files = ["importer.py", "search.py", "service.py", "locate.py", "sql.py"]
    forbidden = {"sqlalchemy", "alembic", "ocint.ctx.db"}
    offenders = []
    for filename in workflow_files:
        imports = _imports(CTX_ROOT / filename)
        if any(name == item or name.startswith(f"{item}.") for name in imports for item in forbidden):
            offenders.append(filename)

    assert offenders == []


def test_workflows_use_focused_repositories_not_broad_ctx_repository() -> None:
    workflow_files = ["importer.py", "search.py", "service.py", "locate.py", "sql.py"]
    offenders = []
    for filename in workflow_files:
        concrete_imports = {
            imported
            for imported in _from_imports(CTX_ROOT / filename)
            if imported[0] in {"ocint.ctx.repository", "ocint.ctx.duckdb_repository"}
        }
        if concrete_imports:
            offenders.append(filename)

    assert offenders == []


def test_workflows_import_repository_protocols() -> None:
    workflow_files = ["importer.py", "search.py", "service.py", "locate.py", "sql.py"]
    offenders = []
    for filename in workflow_files:
        if "ocint.ctx.protocols" not in _imports(CTX_ROOT / filename):
            offenders.append(filename)

    assert offenders == []


def test_search_workflow_uses_search_repository_only() -> None:
    imported = _from_imports(CTX_ROOT / "search.py")

    assert ("ocint.ctx.protocols", "CtxSearchRepositoryProtocol") in imported
    assert not any(module in {"ocint.ctx.repository", "ocint.ctx.duckdb_repository"} for module, _name in imported)


def test_only_cli_constructs_concrete_ctx_repositories() -> None:
    offenders = []
    concrete_names = {
        "CtxImportRepository",
        "CtxLocateRepository",
        "CtxSearchRepository",
        "CtxShowRepository",
        "CtxSqlRepository",
        "CtxStatusRepository",
        "DuckDBCtxImportRepository",
        "DuckDBCtxLocateRepository",
        "DuckDBCtxSearchRepository",
        "DuckDBCtxShowRepository",
        "DuckDBCtxSqlRepository",
        "DuckDBCtxStatusRepository",
    }
    for path in iter_python_files(CTX_ROOT):
        if path.name in {"cli.py", "repository.py", "duckdb_repository.py"}:
            continue
        imported = _from_imports(path)
        concrete_imports = {
            name
            for module, name in imported
            if module in {"ocint.ctx.repository", "ocint.ctx.duckdb_repository"} and name in concrete_names
        }
        if concrete_imports:
            offenders.append(f"{path.relative_to(CTX_ROOT)}: {sorted(concrete_imports)}")

    assert offenders == []


def test_ctx_oo_compatibility_wrappers_are_removed() -> None:
    assert "CtxSearch" not in _top_level_symbols(CTX_ROOT / "search.py")
    assert "CtxService" not in _top_level_symbols(CTX_ROOT / "service.py")
    assert "CtxServiceRepository" not in _top_level_symbols(CTX_ROOT / "service.py")
    assert ("typing", "cast") not in _from_imports(CTX_ROOT / "service.py")


def test_sqlalchemy_statement_access_stays_in_repository() -> None:
    statement_names = {"bindparam", "delete", "func", "select", "text"}
    offenders = []
    for path in iter_python_files(CTX_ROOT):
        if path.name in {"repository.py", "duckdb_repository.py"}:
            continue
        imported_statement_names = {
            name for module, name in _from_imports(path) if module.startswith("sqlalchemy") and name in statement_names
        }
        if imported_statement_names:
            offenders.append(f"{path.relative_to(CTX_ROOT)}: {sorted(imported_statement_names)}")

    assert offenders == []


def test_duckdb_read_repositories_reuse_canonical_read_methods() -> None:
    duplicated_methods = {
        "search_events",
        "find_event",
        "find_session",
        "session_events",
        "event_window",
        "status",
        "sources",
        "load_stable_projection_rows",
    }
    duckdb_read_classes = {
        "DuckDBCtxSearchRepository",
        "DuckDBCtxShowRepository",
        "DuckDBCtxLocateRepository",
        "DuckDBCtxStatusRepository",
        "DuckDBCtxSqlRepository",
    }
    offenders: list[str] = []
    tree = ast.parse((CTX_ROOT / "duckdb_repository.py").read_text())
    for node in tree.body:
        if not isinstance(node, ast.ClassDef) or node.name not in duckdb_read_classes:
            continue
        redefined = sorted(
            child.name for child in node.body if isinstance(child, ast.FunctionDef) and child.name in duplicated_methods
        )
        if redefined:
            offenders.append(f"{node.name}: {redefined}")

    assert offenders == []


def _imports(path: Path) -> set[str]:
    imports: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module)
    return imports


def _from_imports(path: Path) -> set[tuple[str, str]]:
    imports: set[tuple[str, str]] = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.ImportFrom) and node.module:
            imports.update((node.module, alias.name) for alias in node.names)
    return imports


def _top_level_symbols(path: Path) -> set[str]:
    symbols: set[str] = set()
    for node in ast.parse(path.read_text()).body:
        if isinstance(node, ast.ClassDef | ast.FunctionDef):
            symbols.add(node.name)
        elif isinstance(node, ast.Assign):
            symbols.update(target.id for target in node.targets if isinstance(target, ast.Name))
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            symbols.add(node.target.id)
    return symbols
