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
        return Path(home).expanduser()
    if allow_process_home:
        return Path.home()
    return cwd


def _absolute(path: str | Path, *, base: Path | None = None) -> Path:
    expanded = Path(path).expanduser()
    if expanded.is_absolute():
        return expanded
    return (base or Path.cwd()) / expanded


def _config_candidates(env: Mapping[str, str], cwd: Path, *, allow_process_home: bool) -> list[Path]:
    candidates: list[Path] = []
    if xdg_config_home := env.get("XDG_CONFIG_HOME"):
        candidates.append(Path(xdg_config_home).expanduser() / CONFIG_FILE)
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
        return Path(xdg_data_home).expanduser() / "opencode"
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
        resolved_config = _absolute(config_path, base=cwd)
    elif env_config := effective_env.get("OPENCODE_CONFIG"):
        resolved_config = _absolute(env_config, base=cwd)
    else:
        candidates = _config_candidates(effective_env, cwd, allow_process_home=use_process_env)
        resolved_config = next((candidate for candidate in candidates if candidate.exists()), candidates[0])

    data_dir = opencode_data_dir(None if use_process_env else effective_env, cwd=cwd)
    if db_path is not None:
        reject_memory_db_path(db_path)
        resolved_db = _absolute(db_path, base=cwd)
    elif env_db := effective_env.get("OPENCODE_DB"):
        reject_memory_db_path(env_db)
        resolved_db = _absolute(env_db, base=data_dir)
    else:
        resolved_db = data_dir / DEFAULT_DB_NAME

    return ResolvedPaths(
        config_path=resolved_config,
        db_path=resolved_db,
        config_exists=resolved_config.exists(),
        db_exists=resolved_db.exists(),
    )
