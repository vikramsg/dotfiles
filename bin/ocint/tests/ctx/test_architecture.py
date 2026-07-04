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
        if ("ocint.ctx.repository", "CtxRepository") in _from_imports(CTX_ROOT / filename):
            offenders.append(filename)

    assert offenders == []


def test_search_workflow_uses_search_repository_only() -> None:
    imported = _from_imports(CTX_ROOT / "search.py")

    assert ("ocint.ctx.repository", "CtxSearchRepository") in imported
    assert ("ocint.ctx.repository", "CtxRepository") not in imported


def test_ctx_oo_compatibility_wrappers_are_removed() -> None:
    assert "CtxSearch" not in _top_level_symbols(CTX_ROOT / "search.py")
    assert "CtxService" not in _top_level_symbols(CTX_ROOT / "service.py")
    assert "CtxServiceRepository" not in _top_level_symbols(CTX_ROOT / "service.py")
    assert ("typing", "cast") not in _from_imports(CTX_ROOT / "service.py")


def test_sqlalchemy_statement_access_stays_in_repository() -> None:
    statement_names = {"bindparam", "delete", "func", "select", "text"}
    offenders = []
    for path in iter_python_files(CTX_ROOT):
        if path.name == "repository.py":
            continue
        imported_statement_names = {
            name for module, name in _from_imports(path) if module.startswith("sqlalchemy") and name in statement_names
        }
        if imported_statement_names:
            offenders.append(f"{path.relative_to(CTX_ROOT)}: {sorted(imported_statement_names)}")

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
