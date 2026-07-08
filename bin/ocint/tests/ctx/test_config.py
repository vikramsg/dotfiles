from pathlib import Path

import pytest
from ocint.ctx.config import (
    parse_ctx_refresh_ttl,
    resolve_ctx_db_path,
    resolve_ctx_refresh_config,
    resolve_ctx_source_db_path,
)


def test_ctx_db_path_uses_env_override(tmp_path: Path) -> None:
    path = resolve_ctx_db_path(env={"OCINT_CTX_DB": "ctx.sqlite"}, cwd=tmp_path)

    assert path == tmp_path / "ctx.sqlite"


def test_ctx_db_path_canonicalizes_relative_segments(tmp_path: Path) -> None:
    path = resolve_ctx_db_path(env={"OCINT_CTX_DB": "nested/../ctx.sqlite"}, cwd=tmp_path)

    assert path == (tmp_path / "ctx.sqlite").resolve(strict=False)


def test_ctx_source_db_path_canonicalizes_symlink_env_path(tmp_path: Path) -> None:
    source = tmp_path / "source.db"
    source.touch()
    link = tmp_path / "source-link.db"
    link.symlink_to(source)

    path = resolve_ctx_source_db_path(env={"OPENCODE_DB": str(link)}, cwd=tmp_path)

    assert path == source.resolve(strict=False)


def test_ctx_db_path_uses_xdg_state_home(tmp_path: Path) -> None:
    path = resolve_ctx_db_path(env={"XDG_STATE_HOME": str(tmp_path / "state")}, cwd=tmp_path)

    assert path == tmp_path / "state" / "ocint" / "ctx.sqlite"


def test_ctx_db_path_falls_back_to_local_state(tmp_path: Path) -> None:
    path = resolve_ctx_db_path(env={"HOME": str(tmp_path / "home")}, cwd=tmp_path)

    assert path == tmp_path / "home" / ".local" / "state" / "ocint" / "ctx.sqlite"


def test_ctx_db_path_rejects_memory_before_absolutizing(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match=":memory:"):
        resolve_ctx_db_path(env={"OCINT_CTX_DB": ":memory:"}, cwd=tmp_path)


def test_ctx_refresh_ttl_defaults_to_one_hour_and_resolves_artifacts(tmp_path: Path) -> None:
    ctx_db = tmp_path / "nested" / "ctx.sqlite"

    config = resolve_ctx_refresh_config(ctx_db_path=ctx_db, env={})

    assert config.ttl_ms == 3_600_000
    assert config.lock_path == ctx_db.parent / "ctx.sqlite.refresh.lock"
    assert config.log_path == ctx_db.parent / "ctx.sqlite.refresh.log"


@pytest.mark.parametrize(
    ("value", "expected_ms"),
    [("0", 0), ("30s", 30_000), ("10m", 600_000), ("1h", 3_600_000)],
)
def test_ctx_refresh_ttl_parser_accepts_supported_duration_grammar(value: str, expected_ms: int) -> None:
    assert parse_ctx_refresh_ttl(value) == expected_ms


@pytest.mark.parametrize("value", ["", "0s", "10", "1d", "abc", "  "])
def test_ctx_refresh_ttl_parser_rejects_unsupported_values(value: str) -> None:
    with pytest.raises(ValueError, match="OCINT_CTX_REFRESH_TTL"):
        parse_ctx_refresh_ttl(value)
