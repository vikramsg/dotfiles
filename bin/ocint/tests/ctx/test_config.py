from pathlib import Path

import pytest
from ocint.ctx.config import resolve_ctx_backend_config, resolve_ctx_db_path


def test_ctx_db_path_uses_env_override(tmp_path: Path) -> None:
    path = resolve_ctx_db_path(env={"OCINT_CTX_DB": "ctx.sqlite"}, cwd=tmp_path)

    assert path == tmp_path / "ctx.sqlite"


def test_ctx_db_path_uses_xdg_state_home(tmp_path: Path) -> None:
    path = resolve_ctx_db_path(env={"XDG_STATE_HOME": str(tmp_path / "state")}, cwd=tmp_path)

    assert path == tmp_path / "state" / "ocint" / "ctx.sqlite"


def test_ctx_db_path_falls_back_to_local_state(tmp_path: Path) -> None:
    path = resolve_ctx_db_path(env={"HOME": str(tmp_path / "home")}, cwd=tmp_path)

    assert path == tmp_path / "home" / ".local" / "state" / "ocint" / "ctx.sqlite"


def test_ctx_db_path_rejects_memory_before_absolutizing(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match=":memory:"):
        resolve_ctx_db_path(env={"OCINT_CTX_DB": ":memory:"}, cwd=tmp_path)


def test_ctx_backend_defaults_to_sqlite_env_path(tmp_path: Path) -> None:
    config = resolve_ctx_backend_config(env={"OCINT_CTX_DB": "ctx.sqlite"}, cwd=tmp_path)

    assert config.backend == "sqlite"
    assert config.db_path == tmp_path / "ctx.sqlite"


def test_ctx_backend_uses_duckdb_env_path(tmp_path: Path) -> None:
    config = resolve_ctx_backend_config(
        env={"OCINT_CTX_BACKEND": "duckdb", "OCINT_CTX_DUCKDB": "ctx.duckdb"},
        cwd=tmp_path,
    )

    assert config.backend == "duckdb"
    assert config.db_path == tmp_path / "ctx.duckdb"


def test_ctx_backend_cli_value_overrides_environment(tmp_path: Path) -> None:
    config = resolve_ctx_backend_config(
        backend="duckdb",
        env={"OCINT_CTX_BACKEND": "sqlite", "OCINT_CTX_DUCKDB": "ctx.duckdb", "OCINT_CTX_DB": "ctx.sqlite"},
        cwd=tmp_path,
    )

    assert config.backend == "duckdb"
    assert config.db_path == tmp_path / "ctx.duckdb"


@pytest.mark.parametrize(
    ("backend", "env_key"),
    [("sqlite", "OCINT_CTX_DB"), ("duckdb", "OCINT_CTX_DUCKDB")],
)
def test_ctx_backend_rejects_memory_targets(backend: str, env_key: str, tmp_path: Path) -> None:
    with pytest.raises(ValueError, match=":memory:"):
        resolve_ctx_backend_config(backend=backend, env={env_key: ":memory:"}, cwd=tmp_path)


def test_ctx_backend_rejects_unknown_backend(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="Unsupported ocint ctx backend"):
        resolve_ctx_backend_config(env={"OCINT_CTX_BACKEND": "postgres"}, cwd=tmp_path)
