import json
from pathlib import Path

from click.testing import CliRunner


def write_config(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload))
    return path


def test_build_rsync_command_preserves_existing_filters(tmp_path):
    from screenshot.sync import build_rsync_command

    config_file = write_config(
        tmp_path / ".config/screenshot/config.json",
        {
            "screenshot_dir": str(tmp_path / "Screenshots"),
            "sync": {
                "vm_host": "test-vm",
                "remote_dir": "/remote/path/",
            },
        },
    )

    command = build_rsync_command(config_file=config_file)

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
            "sync": {
                "vm_host": "test-vm",
                "remote_dir": "/remote/path/",
            },
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

    sync_module.run_sync()

    assert called == [sync_module.build_rsync_command(config_file=config_file)]


def test_sync_command_cli_prints_command(tmp_path, monkeypatch):
    config_file = write_config(
        tmp_path / ".config/screenshot/config.json",
        {
            "screenshot_dir": str(tmp_path / "Screenshots"),
            "sync": {
                "vm_host": "test-vm",
                "remote_dir": "/remote/path/",
            },
        },
    )
    monkeypatch.setenv("SCREENSHOT_CONFIG_FILE", str(config_file))

    from screenshot.cli import main

    runner = CliRunner()
    result = runner.invoke(main, ["sync", "command"])

    assert result.exit_code == 0
    assert "rsync -avz" in result.output
    assert "test-vm:/remote/path/" in result.output
