from pathlib import Path

from click.testing import CliRunner


def write_config(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f'namespace = "{payload["namespace"]}"\n')
    return path


def test_systemd_install_writes_units_and_enables_path(tmp_path, monkeypatch):
    config_file = write_config(tmp_path / ".config/lch/config.toml", {"namespace": "com.vikramsg.dotfiles"})
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


def test_systemd_install_watcher_writes_explicit_dispatch_command(
    tmp_path, monkeypatch
):
    config_file = write_config(
        tmp_path / ".config/lch/config.toml", {"namespace": "com.example"}
    )
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("LCH_CONFIG_FILE", str(config_file))

    import lch.systemd as systemd_module

    monkeypatch.setattr(systemd_module.sys, "platform", "linux")
    calls: list[list[str]] = []
    monkeypatch.setattr(
        systemd_module.subprocess,
        "run",
        lambda command, **_kwargs: calls.append(command),
    )

    path_unit = systemd_module.install_watcher(
        "lch-example-watcher",
        watch_path=tmp_path / "watched",
        dispatch_command=["/usr/local/bin/example", "run", "source"],
    )
    service_unit = path_unit.with_suffix(".service")

    assert "PathModified=" + str(tmp_path / "watched") in path_unit.read_text()
    assert "ExecStart=/usr/local/bin/example run source" in service_unit.read_text()
    assert calls == [
        ["systemctl", "--user", "daemon-reload"],
        [
            "systemctl",
            "--user",
            "enable",
            "--now",
            "com.example.lch-example-watcher.path",
        ],
    ]


def test_systemd_list_includes_installed_generic_watchers_without_duplicates(
    tmp_path, monkeypatch
):
    config_file = write_config(
        tmp_path / ".config/lch/config.toml", {"namespace": "com.example"}
    )
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("LCH_CONFIG_FILE", str(config_file))

    import lch.systemd as systemd_module

    unit_directory = tmp_path / ".config/systemd/user"
    unit_directory.mkdir(parents=True)
    for label in [
        "com.example.lch-screenshot-clipboard",
        "com.example.lch-example-watcher",
    ]:
        (unit_directory / f"{label}.path").write_text("")
    monkeypatch.setattr(
        systemd_module,
        "is_job_loaded",
        lambda label: label == "com.example.lch-example-watcher",
    )

    jobs = systemd_module.list_known_jobs()

    assert [job.job_id for job in jobs] == [
        "lch-example-watcher",
        "lch-screenshot-clipboard",
    ]
    assert jobs[0].installed is True
    assert jobs[0].loaded is True
    assert jobs[1].installed is True
    assert jobs[1].loaded is False


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
            "journalctl --user -u com.vikramsg.dotfiles.lch-example-watcher.service",
            "journalctl --user -u com.vikramsg.dotfiles.lch-example-watcher.path",
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
    result = runner.invoke(
        cli_module.main, ["logs", "lch-example-watcher", "--lines", "50"]
    )

    assert result.exit_code == 0
    assert calls == [
        [
            "journalctl",
            "--user",
            "-n",
            "50",
            "-u",
            "com.vikramsg.dotfiles.lch-example-watcher.service",
            "-u",
            "com.vikramsg.dotfiles.lch-example-watcher.path",
        ]
    ]


def test_cli_logs_can_follow_journalctl_on_linux(monkeypatch):
    import lch.cli as cli_module

    monkeypatch.setattr(cli_module.sys, "platform", "linux")
    monkeypatch.setattr(
        cli_module,
        "logs_job_systemd",
        lambda _job_id: (
            "journalctl --user -u com.vikramsg.dotfiles.lch-example-watcher.service",
            "journalctl --user -u com.vikramsg.dotfiles.lch-example-watcher.path",
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
    result = runner.invoke(
        cli_module.main,
        ["logs", "lch-example-watcher", "--follow", "--lines", "50"],
    )

    assert result.exit_code == 0
    assert calls == [
        [
            "journalctl",
            "--user",
            "-n",
            "50",
            "-f",
            "-u",
            "com.vikramsg.dotfiles.lch-example-watcher.service",
            "-u",
            "com.vikramsg.dotfiles.lch-example-watcher.path",
        ]
    ]


def test_cli_logs_can_print_journalctl_commands_on_linux(monkeypatch):
    import lch.cli as cli_module

    monkeypatch.setattr(cli_module.sys, "platform", "linux")
    monkeypatch.setattr(
        cli_module,
        "logs_job_systemd",
        lambda _job_id: (
            "journalctl --user -u com.vikramsg.dotfiles.lch-example-watcher.service",
            "journalctl --user -u com.vikramsg.dotfiles.lch-example-watcher.path",
        ),
    )

    runner = CliRunner()
    result = runner.invoke(cli_module.main, ["logs", "lch-example-watcher", "--paths"])

    assert result.exit_code == 0
    assert result.output.splitlines() == [
        "journalctl --user -u com.vikramsg.dotfiles.lch-example-watcher.service",
        "journalctl --user -u com.vikramsg.dotfiles.lch-example-watcher.path",
    ]
