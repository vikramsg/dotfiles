import os
import sys
from collections.abc import Mapping
from pathlib import Path

from opencode_state.db import reject_memory_db_path
from opencode_state.models import ResolvedPaths


CONFIG_FILE = Path("opencode") / "opencode.json"
DEFAULT_DB_NAME = "opencode.db"


def _home(env: Mapping[str, str], *, cwd: Path, allow_process_home: bool) -> Path:
    if home := env.get("HOME"):
        if allow_process_home:
            return Path(home).expanduser()
        return _home_without_process(env, cwd=cwd)
    if allow_process_home:
        return Path.home()
    return cwd


def _expand_user(path: str | Path, *, env: Mapping[str, str], cwd: Path, allow_process_home: bool) -> Path:
    raw_path = os.fspath(path)
    if allow_process_home:
        return Path(raw_path).expanduser()
    if raw_path == "~":
        return _home_without_process(env, cwd=cwd)
    if raw_path.startswith("~/"):
        return _home_without_process(env, cwd=cwd) / raw_path[2:]
    return Path(raw_path)


def _home_without_process(env: Mapping[str, str], *, cwd: Path) -> Path:
    if home := env.get("HOME"):
        if home == "~":
            return cwd
        if home.startswith("~/"):
            return cwd / home[2:]
        return Path(home)
    return cwd


def _absolute(
    path: str | Path,
    *,
    base: Path | None = None,
    env: Mapping[str, str],
    cwd: Path,
    allow_process_home: bool,
) -> Path:
    expanded = _expand_user(path, env=env, cwd=cwd, allow_process_home=allow_process_home)
    if expanded.is_absolute():
        return expanded
    return (base or cwd) / expanded


def _config_candidates(env: Mapping[str, str], cwd: Path, *, allow_process_home: bool) -> list[Path]:
    candidates: list[Path] = []
    if xdg_config_home := env.get("XDG_CONFIG_HOME"):
        candidates.append(
            _absolute(xdg_config_home, base=cwd, env=env, cwd=cwd, allow_process_home=allow_process_home) / CONFIG_FILE
        )
    candidates.append(_home(env, cwd=cwd, allow_process_home=allow_process_home) / ".config" / CONFIG_FILE)

    for parent in (cwd, *cwd.parents):
        repo_config = parent / CONFIG_FILE
        if repo_config.exists():
            candidates.append(repo_config)
            break
    return candidates


def opencode_data_dir(env: Mapping[str, str] | None = None, *, cwd: Path | None = None) -> Path:
    use_process_env = env is None
    effective_env = os.environ if use_process_env else env
    cwd = Path.cwd() if cwd is None else cwd
    if xdg_data_home := effective_env.get("XDG_DATA_HOME"):
        return _absolute(xdg_data_home, base=cwd, env=effective_env, cwd=cwd, allow_process_home=use_process_env) / "opencode"
    if sys.platform == "darwin":
        return _home(effective_env, cwd=cwd, allow_process_home=use_process_env) / "Library" / "Application Support" / "opencode"
    return _home(effective_env, cwd=cwd, allow_process_home=use_process_env) / ".local" / "share" / "opencode"


def resolve_paths(
    *,
    config_path: str | Path | None = None,
    db_path: str | Path | None = None,
    env: Mapping[str, str] | None = None,
    cwd: Path | None = None,
) -> ResolvedPaths:
    use_process_env = env is None
    effective_env = os.environ if use_process_env else env
    cwd = Path.cwd() if cwd is None else cwd

    if config_path is not None:
        resolved_config = _absolute(config_path, base=cwd, env=effective_env, cwd=cwd, allow_process_home=use_process_env)
    elif env_config := effective_env.get("OPENCODE_CONFIG"):
        resolved_config = _absolute(env_config, base=cwd, env=effective_env, cwd=cwd, allow_process_home=use_process_env)
    else:
        candidates = _config_candidates(effective_env, cwd, allow_process_home=use_process_env)
        resolved_config = next((candidate for candidate in candidates if candidate.exists()), candidates[0])

    data_dir = opencode_data_dir(None if use_process_env else effective_env, cwd=cwd)
    if db_path is not None:
        reject_memory_db_path(db_path)
        resolved_db = _absolute(db_path, base=cwd, env=effective_env, cwd=cwd, allow_process_home=use_process_env)
    elif env_db := effective_env.get("OPENCODE_DB"):
        reject_memory_db_path(env_db)
        resolved_db = _absolute(env_db, base=data_dir, env=effective_env, cwd=cwd, allow_process_home=use_process_env)
    else:
        resolved_db = data_dir / DEFAULT_DB_NAME

    return ResolvedPaths(
        config_path=resolved_config,
        db_path=resolved_db,
        config_exists=resolved_config.exists(),
        db_exists=resolved_db.exists(),
    )
