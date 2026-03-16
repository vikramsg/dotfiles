import json
from pathlib import Path

from click.testing import CliRunner


def write_config(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload))
    return path


def test_job_definition_has_expected_label_dispatch_and_watch_path_command(tmp_path, monkeypatch):
    config_file = write_config(tmp_path / ".config/lch/config.json", {"namespace": "com.vikramsg.dotfiles"})
    monkeypatch.setenv("LCH_CONFIG_FILE", str(config_file))

    from lch.jobs import get_job_definition

    job = get_job_definition("lch-screenshot-clipboard")

    assert job.job_id == "lch-screenshot-clipboard"
    assert job.label == "com.vikramsg.dotfiles.lch-screenshot-clipboard"
    assert job.dispatch_command == ["screenshot", "clipboard", "on-event"]
    assert job.watch_path_command == ["screenshot", "watch-path"]


def test_help_lists_install_and_run_commands():
    from lch.cli import main

    runner = CliRunner()
    result = runner.invoke(main, ["--help"])

    assert result.exit_code == 0
    assert "install" in result.output
    assert "run" in result.output
    assert "list" in result.output
    assert "config" in result.output


def test_list_shows_known_jobs_with_install_and_load_status(monkeypatch):
    from types import SimpleNamespace

    import lch.cli as cli_module

    monkeypatch.setattr(
        cli_module,
        "list_known_jobs",
        lambda: [
            SimpleNamespace(
                job_id="lch-screenshot-clipboard",
                installed=True,
                loaded=True,
                label="com.vikramsg.dotfiles.lch-screenshot-clipboard",
            )
        ],
    )

    runner = CliRunner()
    result = runner.invoke(cli_module.main, ["list"])

    assert result.exit_code == 0
    assert "JOB" in result.output
    assert "lch-screenshot-clipboard" in result.output
    assert "yes" in result.output
    assert "com.vikramsg.dotfiles.lch-screenshot-clipboard" in result.output


def test_config_reports_effective_paths_and_namespace_format(monkeypatch):
    import lch.cli as cli_module

    monkeypatch.setattr(
        cli_module,
        "render_lch_config",
        lambda: "CONFIG_FILE  ~/.config/lch/config.json\nNAMESPACE  com.vikramsg.dotfiles\nLCH_BIN  ~/.local/bin/lch",
    )

    runner = CliRunner()
    result = runner.invoke(cli_module.main, ["config"])

    assert result.exit_code == 0
    assert result.output.splitlines() == [
        "CONFIG_FILE  ~/.config/lch/config.json",
        "NAMESPACE  com.vikramsg.dotfiles",
        "LCH_BIN  ~/.local/bin/lch",
    ]
