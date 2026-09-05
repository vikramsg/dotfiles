from collections import UserDict
from dataclasses import dataclass
from pathlib import Path

import pytest
from ocint._config import resolve_paths


@dataclass(frozen=True)
class DataHomeCase:
    value: str
    expected_directory: str


@pytest.fixture(params=[DataHomeCase("data", "data"), DataHomeCase("~/data", "data"), DataHomeCase("", ".local/share")])
def data_home(request: pytest.FixtureRequest) -> DataHomeCase:
    return request.param


def test_env_path_resolution_uses_overrides_and_data_dir_for_relative_db(tmp_path: Path) -> None:
    # GIVEN explicit config and data directories with a relative database name
    config_file = tmp_path / "config.json"
    data_home = tmp_path / "data"
    environment = UserDict(
        OPENCODE_CONFIG=str(config_file),
        OPENCODE_DB="relative.db",
        XDG_DATA_HOME=str(data_home),
        XDG_CONFIG_HOME=str(tmp_path / "xdg_config"),
    )

    # WHEN paths are resolved from supplied inputs
    paths = resolve_paths(env=environment, cwd=tmp_path)

    # THEN overrides are honored and relative database names use the data directory
    assert paths.config_path == config_file
    assert paths.db_path == data_home / "opencode" / "relative.db"


def test_explicit_empty_env_uses_cwd_without_process_home(tmp_path: Path) -> None:
    # GIVEN an explicit empty environment and an isolated working directory
    environment = UserDict[str, str]()

    # WHEN paths are resolved without the process environment
    paths = resolve_paths(env=environment, cwd=tmp_path)

    # THEN both paths use the supplied working directory on every platform
    assert paths.config_path == tmp_path / ".config" / "opencode" / "opencode.json"
    assert paths.db_path == tmp_path / ".local" / "share" / "opencode" / "opencode.db"


def test_default_db_uses_xdg_home_layout(tmp_path: Path) -> None:
    # GIVEN a home distinct from cwd with no database or XDG overrides
    home = tmp_path / "home"
    environment = UserDict(HOME=str(home))

    # WHEN the default database path is resolved
    paths = resolve_paths(env=environment, cwd=tmp_path)

    # THEN macOS and Linux use the same OpenCode location
    assert paths.db_path == home / ".local" / "share" / "opencode" / "opencode.db"


def test_xdg_data_home_controls_db_location(tmp_path: Path, data_home: DataHomeCase) -> None:
    # GIVEN an XDG data override, including the empty-value fallback
    environment = UserDict(HOME=str(tmp_path), XDG_DATA_HOME=data_home.value)

    # WHEN paths are resolved from the supplied working directory
    paths = resolve_paths(env=environment, cwd=tmp_path)

    # THEN nonempty XDG paths are honored and empty values use the standard default
    assert paths.db_path == tmp_path / data_home.expected_directory / "opencode" / "opencode.db"


def test_absolute_db_environment_overrides_data_home(tmp_path: Path) -> None:
    # GIVEN an absolute database override and a different XDG data directory
    expected = tmp_path / "custom" / "history.db"
    environment = UserDict(OPENCODE_DB=str(expected), XDG_DATA_HOME=str(tmp_path / "data"))

    # WHEN the database path is resolved
    paths = resolve_paths(env=environment, cwd=tmp_path)

    # THEN the absolute override is used unchanged
    assert paths.db_path == expected


def test_relative_db_environment_uses_data_directory(tmp_path: Path, data_home: DataHomeCase) -> None:
    # GIVEN a relative database override with either the default or an XDG data directory
    environment = UserDict(HOME=str(tmp_path), XDG_DATA_HOME=data_home.value, OPENCODE_DB="custom.db")

    # WHEN the database path is resolved
    paths = resolve_paths(env=environment, cwd=tmp_path)

    # THEN relative environment paths remain based on the OpenCode data directory
    assert paths.db_path == tmp_path / data_home.expected_directory / "opencode" / "custom.db"


def test_explicit_db_overrides_environment(tmp_path: Path) -> None:
    # GIVEN competing explicit, environment, and XDG paths
    expected = tmp_path / "explicit.db"
    environment = UserDict(OPENCODE_DB=str(tmp_path / "environment.db"), XDG_DATA_HOME=str(tmp_path / "data"))

    # WHEN an explicit database is supplied
    paths = resolve_paths(db_path=expected, env=environment, cwd=tmp_path)

    # THEN it takes precedence over the environment
    assert paths.db_path == expected


def test_relative_explicit_db_uses_cwd(tmp_path: Path) -> None:
    # GIVEN a relative explicit path and conflicting environment paths
    environment = UserDict(OPENCODE_DB="environment.db", XDG_DATA_HOME=str(tmp_path / "data"))

    # WHEN the explicit path is resolved
    paths = resolve_paths(db_path="explicit.db", env=environment, cwd=tmp_path)

    # THEN CLI-relative paths remain based on cwd, not the OpenCode data directory
    assert paths.db_path == tmp_path / "explicit.db"


def test_explicit_memory_db_is_rejected_before_absolutizing(tmp_path: Path) -> None:
    # GIVEN an in-memory database argument and no environment overrides
    environment = UserDict[str, str]()

    # WHEN paths are resolved, THEN in-memory targets are rejected
    with pytest.raises(ValueError, match=":memory:"):
        resolve_paths(db_path=":memory:", env=environment, cwd=tmp_path)


def test_environment_memory_db_is_rejected_before_absolutizing(tmp_path: Path) -> None:
    # GIVEN an in-memory database environment override
    environment = UserDict(OPENCODE_DB=":memory:")

    # WHEN paths are resolved, THEN in-memory targets are rejected
    with pytest.raises(ValueError, match=":memory:"):
        resolve_paths(env=environment, cwd=tmp_path)
