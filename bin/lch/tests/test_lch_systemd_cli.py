import json
from pathlib import Path

from click.testing import CliRunner


def write_config(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload))
    return path


def test_systemd_install_writes_units_and_enables_path(tmp_path, monkeypatch):
    config_file = write_config(tmp_path / ".config/lch/config.json", {"namespace": "com.vikramsg.dotfiles"})
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("LCH_CONFIG_FILE", str(config_file))

    import lch.systemd as systemd_module

    monkeypatch.setattr(systemd_module.sys, "platform", "linux")

    calls: list[list[str]] = []

    def fake_watch_path(job):
        assert job.job_id == "lch-screenshot-clipboard"
        watch_path = tmp_path / "Desktop/Screenshots"
        watch_path.mkdir(parents=True, exist_ok=True)
        return watch_path

    def fake_run(command: list[str], *, check: bool, text: bool, capture_output=False) -> object:
        assert check is True
        assert text is True
        calls.append(command)
        class Result:
            returncode = 0
            stdout = ""
        return Result()

    monkeypatch.setattr(systemd_module, "resolve_watch_path", fake_watch_path)
    monkeypatch.setattr(systemd_module.subprocess, "run", fake_run)

    unit_path = systemd_module.install_job("lch-screenshot-clipboard")

    assert unit_path == tmp_path / ".config/systemd/user/com.vikramsg.dotfiles.lch-screenshot-clipboard.path"
    assert unit_path.exists()
    service_path = tmp_path / ".config/systemd/user/com.vikramsg.dotfiles.lch-screenshot-clipboard.service"
    assert service_path.exists()
    assert f"ExecStart={tmp_path}/.local/bin/lch run lch-screenshot-clipboard" in service_path.read_text()
    assert f"PathModified={tmp_path / 'Desktop/Screenshots'}" in unit_path.read_text()
    assert calls == [
        ["systemctl", "--user", "daemon-reload"],
        ["systemctl", "--user", "enable", "--now", "com.vikramsg.dotfiles.lch-screenshot-clipboard.path"],
    ]


def test_cli_install_uses_systemd_on_linux(monkeypatch):
    import lch.cli as cli_module

    monkeypatch.setattr(cli_module.sys, "platform", "linux")
    monkeypatch.setattr(cli_module, "install_job_systemd", lambda job_id: Path(f"/tmp/{job_id}.path"))
    monkeypatch.setattr(
        cli_module,
        "install_job_launchd",
        lambda _job_id: (_ for _ in ()).throw(AssertionError("launchd install should not be used on linux")),
    )

    runner = CliRunner()
    result = runner.invoke(cli_module.main, ["install", "lch-screenshot-clipboard"])

    assert result.exit_code == 0
    assert result.output.splitlines() == ["/tmp/lch-screenshot-clipboard.path"]


def test_cli_status_uses_systemd_on_linux(monkeypatch):
    import lch.cli as cli_module

    monkeypatch.setattr(cli_module.sys, "platform", "linux")
    monkeypatch.setattr(cli_module, "status_job_systemd", lambda _job_id: "loaded")
    monkeypatch.setattr(
        cli_module,
        "status_job_launchd",
        lambda _job_id: (_ for _ in ()).throw(AssertionError("launchd status should not be used on linux")),
    )

    runner = CliRunner()
    result = runner.invoke(cli_module.main, ["status", "lch-screenshot-clipboard"])

    assert result.exit_code == 0
    assert result.output.splitlines() == ["loaded"]


def test_cli_logs_runs_journalctl_on_linux(monkeypatch):
    import lch.cli as cli_module

    monkeypatch.setattr(cli_module.sys, "platform", "linux")
    monkeypatch.setattr(
        cli_module,
        "logs_job_systemd",
        lambda _job_id: (
            "journalctl --user -u com.vikramsg.dotfiles.lch-screenshot-sync.service",
            "journalctl --user -u com.vikramsg.dotfiles.lch-screenshot-sync.path",
        ),
    )

    calls: list[list[str]] = []

    def fake_run(command: list[str], *, check: bool, text: bool) -> object:
        calls.append(command)
        assert check is True
        assert text is True

        class Result:
            returncode = 0

        return Result()

    monkeypatch.setattr(cli_module.subprocess, "run", fake_run)

    runner = CliRunner()
    result = runner.invoke(cli_module.main, ["logs", "lch-screenshot-sync", "--lines", "50"])

    assert result.exit_code == 0
    assert calls == [
        [
            "journalctl",
            "--user",
            "-n",
            "50",
            "-u",
            "com.vikramsg.dotfiles.lch-screenshot-sync.service",
            "-u",
            "com.vikramsg.dotfiles.lch-screenshot-sync.path",
        ]
    ]


def test_cli_logs_can_follow_journalctl_on_linux(monkeypatch):
    import lch.cli as cli_module

    monkeypatch.setattr(cli_module.sys, "platform", "linux")
    monkeypatch.setattr(
        cli_module,
        "logs_job_systemd",
        lambda _job_id: (
            "journalctl --user -u com.vikramsg.dotfiles.lch-screenshot-sync.service",
            "journalctl --user -u com.vikramsg.dotfiles.lch-screenshot-sync.path",
        ),
    )

    calls: list[list[str]] = []

    def fake_run(command: list[str], *, check: bool, text: bool) -> object:
        calls.append(command)
        assert check is True
        assert text is True

        class Result:
            returncode = 0

        return Result()

    monkeypatch.setattr(cli_module.subprocess, "run", fake_run)

    runner = CliRunner()
    result = runner.invoke(cli_module.main, ["logs", "lch-screenshot-sync", "--follow", "--lines", "50"])

    assert result.exit_code == 0
    assert calls == [
        [
            "journalctl",
            "--user",
            "-n",
            "50",
            "-f",
            "-u",
            "com.vikramsg.dotfiles.lch-screenshot-sync.service",
            "-u",
            "com.vikramsg.dotfiles.lch-screenshot-sync.path",
        ]
    ]


def test_cli_logs_can_print_journalctl_commands_on_linux(monkeypatch):
    import lch.cli as cli_module

    monkeypatch.setattr(cli_module.sys, "platform", "linux")
    monkeypatch.setattr(
        cli_module,
        "logs_job_systemd",
        lambda _job_id: (
            "journalctl --user -u com.vikramsg.dotfiles.lch-screenshot-sync.service",
            "journalctl --user -u com.vikramsg.dotfiles.lch-screenshot-sync.path",
        ),
    )

    runner = CliRunner()
    result = runner.invoke(cli_module.main, ["logs", "lch-screenshot-sync", "--paths"])

    assert result.exit_code == 0
    assert result.output.splitlines() == [
        "journalctl --user -u com.vikramsg.dotfiles.lch-screenshot-sync.service",
        "journalctl --user -u com.vikramsg.dotfiles.lch-screenshot-sync.path",
    ]
