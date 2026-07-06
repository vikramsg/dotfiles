import ast
from collections.abc import Iterator
from pathlib import Path

PACKAGE_ROOT = Path(__file__).parents[2] / "ocint"
CTX_ROOT = PACKAGE_ROOT / "ctx"
PERSISTENCE_FEATURES = {"importing", "locate", "search", "show", "sql", "status"}
ROOT_PERSISTENCE_FILES = {
    "importer.py",
    "locate.py",
    "repository.py",
    "search.py",
    "service.py",
    "sql.py",
    "workflow.py",
}


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


def test_no_root_persistence_modules_or_workflow_file() -> None:
    offenders = sorted(
        path.name for path in CTX_ROOT.iterdir() if path.is_file() and path.name in ROOT_PERSISTENCE_FILES
    )

    assert offenders == []


def test_persistence_features_have_focused_package_shape() -> None:
    missing: list[str] = []
    for feature in sorted(PERSISTENCE_FEATURES):
        feature_root = CTX_ROOT / feature
        for filename in ["__init__.py", "repository.py", "service.py"]:
            path = feature_root / filename
            if not path.is_file():
                missing.append(str(path.relative_to(CTX_ROOT)))

    assert missing == []


def test_service_modules_do_not_own_db_lifecycle() -> None:
    forbidden = {"sqlalchemy", "alembic", "ocint.ctx.db"}
    offenders = []
    for path in _feature_files("service.py"):
        imports = _imports(path)
        if any(name == item or name.startswith(f"{item}.") for name in imports for item in forbidden):
            offenders.append(str(path.relative_to(CTX_ROOT)))

    assert offenders == []


def test_services_only_reference_their_own_repositories() -> None:
    offenders: list[str] = []
    for path in _feature_files("service.py"):
        feature = path.parent.name
        for module, name in _from_imports(path):
            if module.startswith("ocint.ctx.") and module.endswith(".repository"):
                allowed = module == f"ocint.ctx.{feature}.repository"
                if not allowed:
                    offenders.append(f"{path.relative_to(CTX_ROOT)} imports {module}.{name}")

    assert offenders == []


def test_services_do_not_construct_repositories() -> None:
    offenders: list[str] = []
    for path in _feature_files("service.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Call) and _call_name(node).endswith("Repository"):
                offenders.append(f"{path.relative_to(CTX_ROOT)}:{node.lineno}")

    assert offenders == []


def test_ctx_oo_compatibility_wrappers_are_removed() -> None:
    symbols: set[str] = set()
    for path in _feature_files("service.py"):
        symbols.update(_top_level_symbols(path))

    assert "CtxSearch" not in symbols
    assert "CtxService" not in symbols
    assert "CtxServiceRepository" not in symbols


def test_search_package_does_not_import_opencode() -> None:
    offenders = []
    for path in iter_python_files(CTX_ROOT / "search"):
        imports = _imports(path)
        if any(name.startswith("ocint.opencode") for name in imports):
            offenders.append(str(path.relative_to(CTX_ROOT)))

    assert offenders == []


def test_only_importing_service_uses_opencode_source_rows() -> None:
    offenders = []
    for path in iter_python_files(CTX_ROOT):
        imported_modules = _imports(path)
        if (
            "ocint.opencode.models" in imported_modules
            and path.relative_to(CTX_ROOT).as_posix() != "importing/service.py"
        ):
            offenders.append(str(path.relative_to(CTX_ROOT)))

    assert offenders == []


def test_only_cli_instantiates_repositories_and_opencode_source_adapter() -> None:
    offenders: list[str] = []
    for path in iter_python_files(CTX_ROOT):
        if path.relative_to(CTX_ROOT).as_posix() == "cli.py":
            continue
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and _call_name(node).endswith("Repository"):
                offenders.append(f"{path.relative_to(CTX_ROOT)}:{node.lineno}")

    assert offenders == []


def test_only_cli_imports_opencode_repository() -> None:
    offenders = []
    for path in iter_python_files(CTX_ROOT):
        imported = _from_imports(path)
        if ("ocint.opencode.repository", "OpenCodeRepository") in imported:
            offenders.append(str(path.relative_to(CTX_ROOT)))

    assert offenders == ["cli.py"]


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


def test_history_read_model_helper_is_not_persistence_executor() -> None:
    history_path = CTX_ROOT / "history.py"

    assert history_path.is_file()
    forbidden = {"sqlalchemy", "alembic", "ocint.ctx.db"}
    imports = _imports(history_path)
    offenders = sorted(
        name for name in imports if any(name == item or name.startswith(f"{item}.") for item in forbidden)
    )
    assert offenders == []


def test_history_repositories_use_shared_read_model_helper() -> None:
    missing = []
    for feature in ["locate", "search", "show"]:
        repository_path = CTX_ROOT / feature / "repository.py"
        if "ocint.ctx.history" not in _imports(repository_path):
            missing.append(str(repository_path.relative_to(CTX_ROOT)))

    assert missing == []


def test_session_summary_repository_boundaries_are_typed_models() -> None:
    models_path = CTX_ROOT / "models.py"
    assert "CtxSessionSummary" in _top_level_symbols(models_path)

    expected = {
        CTX_ROOT / "show" / "repository.py": "CtxShowRepository",
        CTX_ROOT / "locate" / "repository.py": "CtxLocateRepository",
    }
    offenders: list[str] = []
    for path, class_name in expected.items():
        tree = ast.parse(path.read_text())
        if ("ocint.ctx.models", "CtxSessionSummary") not in _from_imports(path):
            offenders.append(f"{path.relative_to(CTX_ROOT)} does not import CtxSessionSummary")
            continue
        for node in tree.body:
            if isinstance(node, ast.ClassDef) and node.name == class_name:
                find_session = next(
                    (item for item in node.body if isinstance(item, ast.FunctionDef) and item.name == "find_session"),
                    None,
                )
                annotation = find_session.returns if find_session is not None else None
                if annotation is None or ast.unparse(annotation) != "CtxSessionSummary | None":
                    offenders.append(f"{path.relative_to(CTX_ROOT)}.{class_name}.find_session")
                break
        else:
            offenders.append(f"{path.relative_to(CTX_ROOT)} missing {class_name}")

    assert offenders == []


def test_show_and_locate_services_do_not_index_session_mappings() -> None:
    offenders: list[str] = []
    for path in [CTX_ROOT / "show" / "service.py", CTX_ROOT / "locate" / "service.py"]:
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name) and node.value.id == "session":
                offenders.append(f"{path.relative_to(CTX_ROOT)}:{node.lineno}")

    assert offenders == []


def test_history_has_no_session_summary_cast_helper() -> None:
    history_path = CTX_ROOT / "history.py"
    imports = _from_imports(history_path)

    assert "session_summary_row" not in _top_level_symbols(history_path)
    assert ("typing", "cast") not in imports


def test_import_repository_prunes_fts_with_set_based_delete() -> None:
    repository_path = CTX_ROOT / "importing" / "repository.py"
    source = repository_path.read_text()
    normalized = " ".join(source.split())

    assert "bindparam" not in source
    assert "expanding=True" not in source
    assert "DELETE FROM ctx_event_fts" in source
    assert "SELECT id FROM ctx_event WHERE source_id = :source_id" in normalized


def _feature_files(filename: str) -> Iterator[Path]:
    for feature in sorted(PERSISTENCE_FEATURES):
        yield CTX_ROOT / feature / filename


def _call_name(node: ast.Call) -> str:
    if isinstance(node.func, ast.Name):
        return node.func.id
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    return ""


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
