import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

CTX_DB_NAME = "ctx.sqlite"
CTX_DUCKDB_NAME = "ctx.duckdb"
CtxBackend = Literal["sqlite", "duckdb"]


@dataclass(frozen=True)
class CtxBackendConfig:
    backend: CtxBackend
    db_path: Path


def resolve_ctx_db_path(
    *,
    db_path: str | Path | None = None,
    env: Mapping[str, str] | None = None,
    cwd: Path | None = None,
) -> Path:
    """Resolve the ocint-owned ctx index path without creating directories."""
    return resolve_ctx_backend_config(backend="sqlite", db_path=db_path, env=env, cwd=cwd).db_path


def resolve_ctx_backend_config(
    *,
    backend: str | None = None,
    db_path: str | Path | None = None,
    env: Mapping[str, str] | None = None,
    cwd: Path | None = None,
) -> CtxBackendConfig:
    """Resolve the selected ctx backend and persistent DB path without touching disk."""
    use_process_env = env is None
    effective_env = os.environ if use_process_env else env
    cwd = Path.cwd() if cwd is None else cwd
    selected_backend = _resolve_backend(backend=backend, env=effective_env)
    db_name = CTX_DB_NAME if selected_backend == "sqlite" else CTX_DUCKDB_NAME
    env_key = "OCINT_CTX_DB" if selected_backend == "sqlite" else "OCINT_CTX_DUCKDB"

    if db_path is not None:
        _reject_memory_db_path(db_path)
        return CtxBackendConfig(
            backend=selected_backend,
            db_path=_absolute(db_path, env=effective_env, cwd=cwd, allow_process_home=use_process_env),
        )
    if env_path := effective_env.get(env_key):
        _reject_memory_db_path(env_path)
        return CtxBackendConfig(
            backend=selected_backend,
            db_path=_absolute(env_path, env=effective_env, cwd=cwd, allow_process_home=use_process_env),
        )
    if state_home := effective_env.get("XDG_STATE_HOME"):
        return CtxBackendConfig(
            backend=selected_backend,
            db_path=_absolute(state_home, env=effective_env, cwd=cwd, allow_process_home=use_process_env)
            / "ocint"
            / db_name,
        )
    return CtxBackendConfig(
        backend=selected_backend,
        db_path=_home(effective_env, cwd=cwd, allow_process_home=use_process_env)
        / ".local"
        / "state"
        / "ocint"
        / db_name,
    )


def _resolve_backend(*, backend: str | None, env: Mapping[str, str]) -> CtxBackend:
    raw_backend = backend or env.get("OCINT_CTX_BACKEND") or "sqlite"
    normalized = raw_backend.strip().lower()
    if normalized == "sqlite":
        return "sqlite"
    if normalized == "duckdb":
        return "duckdb"
    raise ValueError(f"Unsupported ocint ctx backend: {raw_backend}")


def _reject_memory_db_path(path: str | Path) -> None:
    if os.fspath(path) == ":memory:":
        raise ValueError(":memory: is not a valid ocint ctx DB target")


def _absolute(
    path: str | Path,
    *,
    env: Mapping[str, str],
    cwd: Path,
    allow_process_home: bool,
) -> Path:
    expanded = _expand_user(path, env=env, cwd=cwd, allow_process_home=allow_process_home)
    if expanded.is_absolute():
        return expanded
    return cwd / expanded


def _expand_user(path: str | Path, *, env: Mapping[str, str], cwd: Path, allow_process_home: bool) -> Path:
    raw_path = os.fspath(path)
    if allow_process_home:
        return Path(raw_path).expanduser()
    if raw_path == "~":
        return _home_without_process(env, cwd=cwd)
    if raw_path.startswith("~/"):
        return _home_without_process(env, cwd=cwd) / raw_path[2:]
    return Path(raw_path)


def _home(env: Mapping[str, str], *, cwd: Path, allow_process_home: bool) -> Path:
    if home := env.get("HOME"):
        if allow_process_home:
            return Path(home).expanduser()
        return _home_without_process(env, cwd=cwd)
    if allow_process_home:
        return Path.home()
    return cwd


def _home_without_process(env: Mapping[str, str], *, cwd: Path) -> Path:
    if home := env.get("HOME"):
        if home == "~":
            return cwd
        if home.startswith("~/"):
            return cwd / home[2:]
        return Path(home)
    return cwd
