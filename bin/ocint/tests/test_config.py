from pathlib import Path

import ocint._config as config_module
import pytest
from ocint._config import resolve_paths


def test_env_path_resolution_uses_overrides_and_data_dir_for_relative_db(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_file = tmp_path / "config.json"
    data_home = tmp_path / "data"
    monkeypatch.setenv("OPENCODE_CONFIG", str(config_file))
    monkeypatch.setenv("OPENCODE_DB", "relative.db")
    monkeypatch.setenv("XDG_DATA_HOME", str(data_home))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg_config"))

    paths = resolve_paths()

    assert paths.config_path == config_file
    assert paths.db_path == data_home / "opencode" / "relative.db"


def test_explicit_empty_env_uses_cwd_without_process_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path / "process-home"))

    def fail_home(cls: type[Path]) -> None:
        raise AssertionError("Path.home() should not be called for explicit env")

    monkeypatch.setattr(config_module.Path, "home", classmethod(fail_home))

    paths = resolve_paths(env={}, cwd=tmp_path)

    assert paths.config_path == tmp_path / ".config" / "opencode" / "opencode.json"
    if config_module.sys.platform == "darwin":
        assert paths.db_path == tmp_path / "Library" / "Application Support" / "opencode" / "opencode.db"
    else:
        assert paths.db_path == tmp_path / ".local" / "share" / "opencode" / "opencode.db"


def test_memory_db_is_rejected_before_absolutizing(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match=":memory:"):
        resolve_paths(db_path=":memory:", cwd=tmp_path)

    with pytest.raises(ValueError, match=":memory:"):
        resolve_paths(env={"OPENCODE_DB": ":memory:"}, cwd=tmp_path)
