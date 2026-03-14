import json
from pathlib import Path


def write_config(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload))
    return path


def test_load_config_reads_screenshot_and_sync_settings(tmp_path, monkeypatch):
    monkeypatch.delenv("SCREENSHOT_DIR", raising=False)
    config_file = write_config(
        tmp_path / ".config/screenshot/config.json",
        {
            "screenshot_dir": "~/Screenshots",
            "clipboard_history_limit": 7,
            "sync": {
                "vm_host": "test-vm",
                "remote_dir": "~/Pictures/Screenshots/",
            },
        },
    )

    from screenshot.config import DEFAULT_FILENAME_PATTERNS, load_config

    config = load_config(config_file=config_file)

    assert config.screenshot_dir == Path.home() / "Screenshots"
    assert config.clipboard_history_limit == 7
    assert config.sync.vm_host == "test-vm"
    assert config.sync.remote_dir == "~/Pictures/Screenshots/"
    assert config.filename_patterns == DEFAULT_FILENAME_PATTERNS


def test_load_config_uses_defaults_when_values_are_omitted(tmp_path, monkeypatch):
    monkeypatch.delenv("SCREENSHOT_DIR", raising=False)
    config_file = write_config(
        tmp_path / ".config/screenshot/config.json",
        {
            "sync": {
                "vm_host": "test-vm",
                "remote_dir": "/remote/path",
            }
        },
    )

    from screenshot.config import DEFAULT_CLIPBOARD_HISTORY_LIMIT, DEFAULT_FILENAME_PATTERNS, load_config

    config = load_config(config_file=config_file)

    assert config.screenshot_dir == Path.home() / "Screenshots"
    assert config.clipboard_history_limit == DEFAULT_CLIPBOARD_HISTORY_LIMIT == 5
    assert config.filename_patterns == DEFAULT_FILENAME_PATTERNS


def test_screenshot_dir_env_override_wins_over_config(tmp_path, monkeypatch):
    config_file = write_config(
        tmp_path / ".config/screenshot/config.json",
        {
            "screenshot_dir": "~/Ignored",
            "sync": {
                "vm_host": "test-vm",
                "remote_dir": "/remote/path",
            },
        },
    )
    monkeypatch.setenv("SCREENSHOT_DIR", "/tmp/screenshots")

    from screenshot.config import load_config

    config = load_config(config_file=config_file)

    assert config.screenshot_dir == Path("/tmp/screenshots")


def test_load_config_uses_default_file_location_when_not_explicit(tmp_path, monkeypatch):
    home = tmp_path / "home"
    config_file = write_config(
        home / ".config/screenshot/config.json",
        {
            "sync": {
                "vm_host": "demo-vm",
                "remote_dir": "/srv/screenshots",
            },
        },
    )
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("SCREENSHOT_CONFIG_FILE", str(config_file))
    monkeypatch.delenv("SCREENSHOT_DIR", raising=False)

    from screenshot.config import load_config

    config = load_config()

    assert config.screenshot_dir == home / "Screenshots"
    assert config.sync.vm_host == "demo-vm"
