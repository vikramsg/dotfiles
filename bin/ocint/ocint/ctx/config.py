import os
from collections.abc import Mapping
from pathlib import Path

from ocint._config import resolve_paths
from ocint.ctx.models import CtxRefreshConfig

CTX_DB_NAME = "ctx.sqlite"
DEFAULT_CTX_REFRESH_TTL = "1h"
CTX_DB_BUSY_TIMEOUT_MS = 5_000


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
        return _canonical_path(_absolute(db_path, env=effective_env, cwd=cwd, allow_process_home=use_process_env))
    if env_path := effective_env.get("OCINT_CTX_DB"):
        _reject_memory_db_path(env_path)
        return _canonical_path(_absolute(env_path, env=effective_env, cwd=cwd, allow_process_home=use_process_env))
    if state_home := effective_env.get("XDG_STATE_HOME"):
        return _canonical_path(
            _absolute(state_home, env=effective_env, cwd=cwd, allow_process_home=use_process_env)
            / "ocint"
            / CTX_DB_NAME
        )
    return _canonical_path(
        _home(effective_env, cwd=cwd, allow_process_home=use_process_env) / ".local" / "state" / "ocint" / CTX_DB_NAME
    )


def resolve_ctx_source_db_path(
    *,
    source_db: str | Path | None = None,
    env: Mapping[str, str] | None = None,
    cwd: Path | None = None,
) -> Path:
    """Resolve the OpenCode source path for ctx identity without opening the source DB."""
    resolved = (
        resolve_paths(db_path=source_db, env=env, cwd=cwd).db_path
        if source_db is not None
        else resolve_paths(env=env, cwd=cwd).db_path
    )
    return _canonical_path(resolved)


def resolve_ctx_refresh_config(
    *,
    ctx_db_path: Path,
    env: Mapping[str, str] | None = None,
) -> CtxRefreshConfig:
    """Resolve typed ctx refresh policy and artifact paths beside the ctx DB."""
    effective_env = os.environ if env is None else env
    ttl = parse_ctx_refresh_ttl(effective_env.get("OCINT_CTX_REFRESH_TTL", DEFAULT_CTX_REFRESH_TTL))
    return CtxRefreshConfig(
        ttl_ms=ttl,
        lock_path=ctx_db_path.parent / f"{ctx_db_path.name}.refresh.lock",
        log_path=ctx_db_path.parent / f"{ctx_db_path.name}.refresh.log",
    )


def reject_ctx_source_db_alias(*, ctx_db_path: Path, source_db_path: Path) -> None:
    """Reject configurations that would open the OpenCode source as the ctx DB."""
    ctx_resolved = ctx_db_path.expanduser().resolve(strict=False)
    source_resolved = source_db_path.expanduser().resolve(strict=False)

    aliases = ctx_resolved == source_resolved
    if not aliases and ctx_db_path.exists() and source_db_path.exists():
        aliases = ctx_db_path.samefile(source_db_path)

    if aliases:
        raise ValueError("ocint ctx DB must not be the same file as the OpenCode source DB")


def _canonical_path(path: Path) -> Path:
    return path.expanduser().resolve(strict=False)


def parse_ctx_refresh_ttl(value: str) -> int:
    """Parse OCINT_CTX_REFRESH_TTL into milliseconds using the supported tiny duration grammar."""
    raw = value.strip()
    if raw == "0":
        return 0
    if len(raw) < 2:
        raise ValueError(_ttl_error(value))
    unit = raw[-1]
    amount_text = raw[:-1]
    if unit not in {"s", "m", "h"} or not amount_text.isdecimal():
        raise ValueError(_ttl_error(value))
    amount = int(amount_text)
    if amount <= 0:
        raise ValueError(_ttl_error(value))
    multiplier = {"s": 1_000, "m": 60_000, "h": 3_600_000}[unit]
    return amount * multiplier


def _ttl_error(value: str) -> str:
    return f"invalid OCINT_CTX_REFRESH_TTL {value!r}; use 0, or a duration like 30s, 10m, or 1h"


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
