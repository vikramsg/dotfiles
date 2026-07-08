import ast
from collections.abc import Iterator
from pathlib import Path

PACKAGE_ROOT = Path(__file__).parents[2] / "ocint"
CTX_ROOT = PACKAGE_ROOT / "ctx"
PERSISTENCE_FEATURES = {"importing", "locate", "refresh", "search", "show", "sql", "status"}
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


def test_ctx_db_package_owns_lifecycle_schema_and_migrations() -> None:
    assert (CTX_ROOT / "db" / "__init__.py").is_file()
    assert (CTX_ROOT / "db" / "connection.py").is_file()
    assert (CTX_ROOT / "db" / "schema.py").is_file()
    assert (CTX_ROOT / "db" / "migrations" / "env.py").is_file()
    assert (CTX_ROOT / "db" / "migrations" / "versions" / "__init__.py").is_file()

    assert not (CTX_ROOT / "db.py").exists()
    assert not (CTX_ROOT / "schema.py").exists()
    assert not (CTX_ROOT / "migrations" / "env.py").exists()
    root_version_files = sorted(
        path.name for path in (CTX_ROOT / "migrations" / "versions").glob("*.py") if path.name != "__init__.py"
    )
    assert root_version_files == []


def test_ctx_migration_uses_date_slug_revision_convention() -> None:
    versions_dir = CTX_ROOT / "db" / "migrations" / "versions"
    version_files = sorted(path.name for path in versions_dir.glob("*.py") if path.name != "__init__.py")

    assert version_files == ["20260704_create_ctx_index.py", "20260707_ctx_refresh_state.py"]
    migration_source = (versions_dir / "20260704_create_ctx_index.py").read_text()
    assert 'revision = "20260704_create_ctx_index"' in migration_source
    refresh_migration_source = (versions_dir / "20260707_ctx_refresh_state.py").read_text()
    assert 'revision = "20260707_ctx_refresh_state"' in refresh_migration_source
    assert 'down_revision = "20260704_create_ctx_index"' in refresh_migration_source
    assert "0001" not in migration_source


def test_ctx_alembic_file_template_uses_date_slug_without_revision_prefix() -> None:
    connection_source = (CTX_ROOT / "db" / "connection.py").read_text()

    assert "file_template" in connection_source
    assert "year" in connection_source
    assert "month" in connection_source
    assert "day" in connection_source
    assert "slug" in connection_source
    assert "%%(rev)" not in connection_source
    assert "%(rev)" not in connection_source
    assert "0001" not in connection_source


def test_ctx_db_schema_has_no_public_sql_view_contract_globals() -> None:
    schema_path = CTX_ROOT / "db" / "schema.py"
    symbols = _top_level_symbols(schema_path)

    assert "metadata" in symbols
    assert "ctx_session" in symbols
    assert "ctx_event" in symbols
    assert "STABLE_CTX_VIEW_COLUMNS" not in symbols
    assert "STABLE_CTX_VIEWS" not in symbols
    assert "CREATE VIEW" not in schema_path.read_text()


def test_sql_models_own_stable_view_config_without_sqlite_backend_import() -> None:
    models_path = CTX_ROOT / "sql" / "models.py"

    assert models_path.is_file()
    assert "sqlite3" not in _imports(models_path)
    assert "CtxSqlConfig" in _top_level_symbols(models_path)
    assert "default_ctx_sql_config" in _top_level_symbols(models_path)
    assert "stable_view_create_statement" in _top_level_symbols(models_path)
    assert "stable_view_create_statements" in _top_level_symbols(models_path)


def test_root_cli_package_owns_output_context_injection() -> None:
    assert (PACKAGE_ROOT / "cli" / "__init__.py").is_file()
    assert (PACKAGE_ROOT / "cli" / "_render.py").is_file()
    assert not (PACKAGE_ROOT / "cli.py").exists()

    model_symbols = _top_level_symbols(PACKAGE_ROOT / "_models.py")
    assert "CliContext" in model_symbols
    assert "CliOutput" in model_symbols
    assert "CliProgress" in model_symbols


def test_feature_clis_use_injected_output_without_direct_echo_or_rich_imports() -> None:
    offenders: list[str] = []
    for path in [CTX_ROOT / "cli.py", PACKAGE_ROOT / "state" / "cli.py"]:
        source = path.read_text()
        imports = _imports(path)
        from_imports = _from_imports(path)
        if "click.echo" in source or "click.secho" in source:
            offenders.append(f"{path.relative_to(PACKAGE_ROOT)} uses direct click echo")
        if any(item.startswith("rich") for item in imports):
            offenders.append(f"{path.relative_to(PACKAGE_ROOT)} imports rich")
        if ("ocint._models", "CliContext") not in from_imports:
            offenders.append(f"{path.relative_to(PACKAGE_ROOT)} does not import CliContext")

    assert offenders == []


def test_ctx_import_uses_generator_events_without_legacy_import_history_wrapper() -> None:
    service_path = CTX_ROOT / "importing" / "service.py"
    package_path = CTX_ROOT / "importing" / "__init__.py"

    service_source = service_path.read_text()
    package_source = package_path.read_text()
    assert "def import_history_events(" in service_source
    assert "def import_history(" not in service_source
    assert "import_history_events" in package_source
    assert 'import_history"' not in package_source


def test_ctx_import_source_adapter_is_message_part_only_without_raw_event_fallbacks() -> None:
    service_source = (CTX_ROOT / "importing" / "service.py").read_text()
    repository_source = (PACKAGE_ROOT / "opencode" / "repository.py").read_text()
    models_source = (PACKAGE_ROOT / "opencode" / "models.py").read_text()
    schema_source = (PACKAGE_ROOT / "opencode" / "schema.py").read_text()

    assert "transcript_event_batches" in service_source
    assert "transcript_event_batches" in repository_source
    assert "transcript_event_keys" in service_source
    assert "session_message_keys" in service_source
    assert "source_table_watermarks" in service_source
    assert "transcript_event_count" in repository_source
    assert "all_transcript_events" not in service_source
    assert "all_transcript_events" not in repository_source
    assert "def _batches" not in service_source
    assert "fetchmany" in repository_source
    assert "all_unified_events" not in service_source
    assert ".events(" not in service_source
    for forbidden in [
        "def events(",
        "def all_unified_events(",
        "def _events(",
        "def _unified_event(",
        'source_table="event"',
        'source_table == "event"',
        "OpenCodeEventData",
        "OpenCodeEventRow",
    ]:
        assert forbidden not in repository_source
    assert "OpenCodeTranscriptEventRow" in models_source
    assert "OpenCodeUnifiedEventRow" not in models_source
    assert "OpenCodeEventData" not in models_source
    assert "OpenCodeEventRow" not in models_source
    assert 'Literal["message", "part"]' in models_source
    assert "event_session_id_expr" not in schema_source
    assert "event_type_expr" not in schema_source
    assert "event_time_created_expr" not in schema_source


def test_ctx_spec_documents_import_generator_contract() -> None:
    spec_source = (PACKAGE_ROOT.parent / "docs" / "spec.md").read_text()

    assert "def import_history_events(" in spec_source
    assert "CtxImportProgress" in spec_source
    assert "CtxImportResult" in spec_source
    assert "CtxImportEvent" in spec_source
    assert "full: bool" not in spec_source
    assert "def import_history(" not in spec_source


def test_status_readiness_uses_sql_contract_without_hard_coded_stable_views() -> None:
    repository_source = (CTX_ROOT / "status" / "repository.py").read_text()

    assert "CtxSqlConfig" in repository_source
    assert ".stable_views" in repository_source
    for view_name in ["ctx_sessions", "ctx_events", "ctx_files_touched", "ctx_sources"]:
        assert view_name not in repository_source


def test_status_readiness_receives_expected_revision_without_hard_coding() -> None:
    service_source = (CTX_ROOT / "status" / "service.py").read_text()
    repository_source = (CTX_ROOT / "status" / "repository.py").read_text()

    assert "expected_revision" in service_source
    assert "expected_revision" in repository_source
    for source in [service_source, repository_source]:
        assert "20260704_create_ctx_index" not in source
        assert "0001_ctx_index" not in source


def test_ctx_db_package_exposes_current_head_revision_lookup() -> None:
    connection_source = (CTX_ROOT / "db" / "connection.py").read_text()
    package_source = (CTX_ROOT / "db" / "__init__.py").read_text()

    assert "current_ctx_head_revision" in connection_source
    assert "current_ctx_head_revision" in package_source
    assert "ScriptDirectory" in connection_source


def test_status_repository_row_loaders_do_not_encode_unready_fallbacks() -> None:
    repository_path = CTX_ROOT / "status" / "repository.py"
    status_source = _class_method_source(repository_path, "CtxStatusRepository", "status")
    sources_source = _class_method_source(repository_path, "CtxStatusRepository", "sources")

    assert "self.index_ready" not in status_source
    assert "self.index_ready" not in sources_source
    assert "index_ready =" not in status_source
    assert "index_ready=False" not in status_source
    assert "db_exists=self.db_path.exists()" not in status_source
    assert "return []" not in sources_source


def test_sql_repository_loads_projection_rows_without_sandbox_policy() -> None:
    repository_path = CTX_ROOT / "sql" / "repository.py"
    source = repository_path.read_text()
    symbols = _top_level_symbols(repository_path)

    assert "sqlite3" not in _imports(repository_path)
    assert "ocint._sqlsafe" not in _imports(repository_path)
    assert "Authorizer" not in symbols
    assert "_ALLOWED_SANDBOX_ACTIONS" not in symbols
    assert "_SANDBOX_INTEGER_COLUMNS" not in symbols
    assert "execute_stable_view_query" not in symbols
    assert "load_stable_projection_rows" in source


def test_status_service_requires_non_nullable_repository() -> None:
    service_source = (CTX_ROOT / "status" / "service.py").read_text()

    assert "CtxStatusRepository | None" not in service_source
    assert "repository is None" not in service_source


def test_cli_and_render_use_typed_command_modes_without_callback_repository_helpers() -> None:
    cli_source = (CTX_ROOT / "cli.py").read_text()
    render_source = (CTX_ROOT / "render.py").read_text()

    assert "_with_existing_ctx_repository" not in cli_source
    assert "_with_ctx_repository" not in cli_source
    assert 'refresh != "off"' not in cli_source
    assert 'output_format == "json"' not in cli_source
    assert 'output_format == "csv"' not in cli_source
    assert "RefreshMode" in cli_source
    assert "CtxSqlOutputFormat" in cli_source
    assert 'output_format == "markdown"' not in render_source
    assert 'mode == "log"' not in render_source
    assert 'mode == "full"' not in render_source
    assert 'mode != "full"' not in render_source


def test_refresh_attempt_lifecycle_transitions_are_service_owned() -> None:
    cli_source = (CTX_ROOT / "cli.py").read_text()
    refresh_service_symbols = _top_level_symbols(CTX_ROOT / "refresh" / "service.py")

    assert "begin_refresh_attempt" in refresh_service_symbols
    assert "record_refresh_attempt_failure" in refresh_service_symbols
    assert ".mark_attempt_started" not in cli_source
    assert ".mark_attempt_failed" not in cli_source
    assert "CtxRefreshFailure(" not in cli_source


def test_only_cli_imports_ctx_db_lifecycle_helpers() -> None:
    allowed = {"cli.py", "db/__init__.py"}
    lifecycle_names = {"create_ctx_engine", "ctx_session", "migrate_ctx_db"}
    offenders: list[str] = []
    for path in iter_python_files(CTX_ROOT):
        relative = path.relative_to(CTX_ROOT).as_posix()
        if relative in allowed:
            continue
        for module, name in _from_imports(path):
            if module in {"ocint.ctx.db", "ocint.ctx.db.connection"} and name in lifecycle_names:
                offenders.append(f"{relative} imports {module}.{name}")

    assert offenders == []


def test_repositories_and_migrations_import_physical_schema_from_db_package() -> None:
    expected_schema_importers = [
        CTX_ROOT / "importing" / "repository.py",
        CTX_ROOT / "status" / "repository.py",
        CTX_ROOT / "db" / "migrations" / "env.py",
        CTX_ROOT / "db" / "migrations" / "versions" / "20260704_create_ctx_index.py",
    ]
    offenders: list[str] = []
    for path in expected_schema_importers:
        imports = _imports(path) if path.exists() else set()
        if "ocint.ctx.db.schema" not in imports:
            offenders.append(str(path.relative_to(CTX_ROOT)))

    stale_imports = [
        str(path.relative_to(CTX_ROOT)) for path in iter_python_files(CTX_ROOT) if "ocint.ctx.schema" in _imports(path)
    ]
    assert offenders == []
    assert stale_imports == []


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
        if "db/migrations/versions" in path.relative_to(CTX_ROOT).as_posix():
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


def test_import_repository_prunes_fts_with_seen_key_temp_table() -> None:
    repository_path = CTX_ROOT / "importing" / "repository.py"
    source = repository_path.read_text()
    normalized = " ".join(source.split())

    assert "bindparam" not in source
    assert "expanding=True" not in source
    assert "DELETE FROM ctx_event_fts" in source
    assert "temp_ctx_seen_event_keys" in source
    assert "NOT EXISTS" in normalized


def test_import_repository_upserts_changed_events_without_source_wide_clear() -> None:
    repository_source = (CTX_ROOT / "importing" / "repository.py").read_text()
    service_source = (CTX_ROOT / "importing" / "service.py").read_text()

    assert "def upsert_events_with_files(" in repository_source
    assert "clear_source_rows" not in repository_source
    assert "tuple_(" in repository_source
    assert "ctx_event_fts(search_text, event_pk, event_id, source_table)" in repository_source
    assert "for index, event in enumerate(events" not in service_source
    assert "repository.upsert_events_with_files" in service_source
    assert "transcript_event_batches_for_keys" in service_source


def _class_method_source(path: Path, class_name: str, method_name: str) -> str:
    source = path.read_text()
    for node in ast.parse(source).body:
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            for item in node.body:
                if isinstance(item, ast.FunctionDef) and item.name == method_name:
                    return ast.get_source_segment(source, item) or ""
    raise AssertionError(f"Missing {class_name}.{method_name} in {path}")


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
