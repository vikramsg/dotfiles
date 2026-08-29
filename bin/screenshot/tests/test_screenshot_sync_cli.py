import json
from pathlib import Path

from click.testing import CliRunner


def write_config(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload))
    return path


def system_sync(local_dir: str, vm_host: str, remote_dir: str) -> dict:
    return {
        "sources": [
            {
                "id": "system",
                "local_dir": local_dir,
                "vm_host": vm_host,
                "remote_dir": remote_dir,
                "include": ["Screenshot *.png", "Screen Shot *.png"],
            }
        ]
    }


def test_build_rsync_command_preserves_existing_filters(tmp_path):
    from screenshot.sync import build_rsync_command

    config_file = write_config(
        tmp_path / ".config/screenshot/config.json",
        {
            "screenshot_dir": str(tmp_path / "Screenshots"),
                "sync": system_sync(str(tmp_path / "Screenshots"), "test-vm", "/remote/path/"),
        },
    )

    command = build_rsync_command("system", config_file=config_file)

    assert command[0] == "rsync"
    assert "-avz" in command
    assert "--include=Screenshot *.png" in command
    assert "--include=Screen Shot *.png" in command
    assert "--exclude=*" in command
    assert command[-2] == f"{(tmp_path / 'Screenshots').resolve()}/"
    assert command[-1] == "test-vm:/remote/path/"


def test_sync_run_executes_rsync_command(tmp_path, monkeypatch):
    config_file = write_config(
        tmp_path / ".config/screenshot/config.json",
        {
            "screenshot_dir": str(tmp_path / "Screenshots"),
                "sync": system_sync(str(tmp_path / "Screenshots"), "test-vm", "/remote/path/"),
        },
    )
    monkeypatch.setenv("SCREENSHOT_CONFIG_FILE", str(config_file))

    import screenshot.sync as sync_module

    called: list[list[str]] = []

    def fake_run(command: list[str], *, check: bool, text: bool) -> None:
        assert check is True
        assert text is True
        called.append(command)

    monkeypatch.setattr(sync_module.subprocess, "run", fake_run)

    sync_module.run_sync("system")

    assert called == [
        ["ssh", "test-vm", "mkdir", "-p", "/remote/path/"],
        sync_module.build_rsync_command("system", config_file=config_file),
    ]


def test_sync_command_cli_prints_command(tmp_path, monkeypatch):
    config_file = write_config(
        tmp_path / ".config/screenshot/config.json",
        {
            "screenshot_dir": str(tmp_path / "Screenshots"),
                "sync": system_sync(str(tmp_path / "Screenshots"), "test-vm", "/remote/path/"),
        },
    )
    monkeypatch.setenv("SCREENSHOT_CONFIG_FILE", str(config_file))

    from screenshot.cli import main

    runner = CliRunner()
    result = runner.invoke(main, ["sync", "command"])

    assert result.exit_code == 0
    assert "rsync -avz" in result.output
    assert "test-vm:/remote/path/" in result.output


def test_sync_list_cli_prints_configured_source_ids_in_order(tmp_path, monkeypatch):
    config_file = write_config(
        tmp_path / ".config/screenshot/config.json",
        {
            "sync": {
                "sources": [
                    {
                        "id": "system",
                        "local_dir": "~/Desktop/Screenshots",
                        "vm_host": "test-vm",
                        "remote_dir": "/remote/system/",
                        "include": ["*.png"],
                    },
                    {
                        "id": "screenshot-archive",
                        "local_dir": "~/Pictures/screenshot-archive",
                        "vm_host": "test-vm",
                        "remote_dir": "/remote/archive/",
                        "include": ["*.png"],
                    },
                ]
            }
        },
    )
    monkeypatch.setenv("SCREENSHOT_CONFIG_FILE", str(config_file))

    from screenshot.cli import main

    result = CliRunner().invoke(main, ["sync", "list"])

    assert result.exit_code == 0
    assert result.output.splitlines() == ["system", "screenshot-archive"]


def test_sync_list_cli_is_empty_without_configured_sources(tmp_path, monkeypatch):
    config_file = write_config(tmp_path / "screenshot.json", {})
    monkeypatch.setenv("SCREENSHOT_CONFIG_FILE", str(config_file))

    from screenshot.cli import main

    result = CliRunner().invoke(main, ["sync", "list"])

    assert result.exit_code == 0
    assert result.output == ""


def test_archive_source_applies_configured_exclusions(tmp_path):
    from screenshot.sync import build_rsync_command

    config_file = write_config(
        tmp_path / "screenshot.json",
        {
            "sync": {
                "sources": [
                    {
                        "id": "screenshot-archive",
                        "local_dir": str(tmp_path / "history"),
                        "vm_host": "test-vm",
                        "remote_dir": "/remote/archive/",
                        "include": ["*.png"],
                        "exclude": ["*_preview.png", "*_thumb.png"],
                    }
                ]
            }
        },
    )

    command = build_rsync_command("screenshot-archive", config_file=config_file)

    assert command[0:2] == ["rsync", "-avz"]
    assert "--exclude=*_preview.png" in command
    assert "--exclude=*_thumb.png" in command
    assert "--include=*.png" in command
    assert command[-1] == "test-vm:/remote/archive/"
