import json
from pathlib import Path


def write_config(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload))
    return path


def test_load_config_reads_namespace_from_effective_file(tmp_path, monkeypatch):
    config_file = write_config(
        tmp_path / ".config/lch/config.json",
        {
            "namespace": "com.example.dotfiles",
        },
    )
    monkeypatch.setenv("LCH_CONFIG_FILE", str(config_file))

    from lch.config import load_config

    config = load_config()

    assert config.namespace == "com.example.dotfiles"


def test_get_job_definition_uses_namespace_from_config(tmp_path, monkeypatch):
    config_file = write_config(
        tmp_path / ".config/lch/config.json",
        {
            "namespace": "com.example.dotfiles",
        },
    )
    monkeypatch.setenv("LCH_CONFIG_FILE", str(config_file))

    from lch.jobs import get_job_definition

    job = get_job_definition("lch-screenshot-clipboard")

    assert job.label == "com.example.dotfiles.lch-screenshot-clipboard"


def test_sync_job_definition_uses_namespace_from_config(tmp_path, monkeypatch):
    config_file = write_config(
        tmp_path / ".config/lch/config.json",
        {
            "namespace": "com.example.dotfiles",
        },
    )
    monkeypatch.setenv("LCH_CONFIG_FILE", str(config_file))

    from lch.jobs import get_job_definition

    job = get_job_definition("lch-screenshot-sync")

    assert job.label == "com.example.dotfiles.lch-screenshot-sync"


def test_load_config_uses_default_path_when_override_is_absent(tmp_path, monkeypatch):
    home = tmp_path / "home"
    config_file = write_config(
        home / ".config/lch/config.json",
        {
            "namespace": "com.example.default",
        },
    )
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("LCH_CONFIG_FILE", raising=False)

    from lch.config import get_config_file, load_config

    assert get_config_file() == config_file
    assert load_config().namespace == "com.example.default"
