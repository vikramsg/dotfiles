from click.testing import CliRunner


def test_job_definition_has_expected_label_dispatch_and_watch_path_command():
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
