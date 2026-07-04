import os
from collections.abc import Mapping
from pathlib import Path

CTX_DB_NAME = "ctx.sqlite"


def resolve_ctx_db_path(
    *,
    db_path: str | Path | None = None,
    env: Mapping[str, str] | None = None,
    cwd: Path | None = None,
) -> Path:
    """Resolve the ocint-owned ctx index path without creating directories."""
    use_process_env = env is None
    effective_env = os.environ if use_process_env else env
    cwd = Path.cwd() if cwd is None else cwd

    if db_path is not None:
        _reject_memory_db_path(db_path)
        return _absolute(db_path, env=effective_env, cwd=cwd, allow_process_home=use_process_env)
    if env_path := effective_env.get("OCINT_CTX_DB"):
        _reject_memory_db_path(env_path)
        return _absolute(env_path, env=effective_env, cwd=cwd, allow_process_home=use_process_env)
    if state_home := effective_env.get("XDG_STATE_HOME"):
        return (
            _absolute(state_home, env=effective_env, cwd=cwd, allow_process_home=use_process_env)
            / "ocint"
            / CTX_DB_NAME
        )
    return (
        _home(effective_env, cwd=cwd, allow_process_home=use_process_env) / ".local" / "state" / "ocint" / CTX_DB_NAME
    )


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
