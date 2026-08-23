from click.testing import CliRunner

from opener_tunnel.cli import main


def test_cli_exposes_run_without_doctor():
    result = CliRunner().invoke(main, ["--help"])

    assert result.exit_code == 0
    assert "run" in result.output
    assert "doctor" not in result.output
