from pathlib import Path

import pytest
from ocint.ctx.config import resolve_ctx_db_path


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
