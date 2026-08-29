import plistlib
from pathlib import Path

from click.testing import CliRunner


def write_config(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f'namespace = "{payload["namespace"]}"\n')
    return path


def test_launch_agent_paths_follow_label_conventions(tmp_path, monkeypatch):
    config_file = write_config(tmp_path / ".config/lch/config.toml", {"namespace": "com.vikramsg.dotfiles"})
    monkeypatch.setenv("LCH_CONFIG_FILE", str(config_file))

    from lch.jobs import get_job_definition
    from lch.launchd import get_job_paths

    job = get_job_definition("lch-screenshot-clipboard")
    paths = get_job_paths(job, home=tmp_path)

    assert paths.plist_path == tmp_path / "Library/LaunchAgents/com.vikramsg.dotfiles.lch-screenshot-clipboard.plist"
    assert paths.stdout_log_path == tmp_path / "Library/Logs/com.vikramsg.dotfiles.lch-screenshot-clipboard.out.log"
    assert paths.stderr_log_path == tmp_path / "Library/Logs/com.vikramsg.dotfiles.lch-screenshot-clipboard.err.log"


def test_build_launch_agent_plist_uses_watch_path_and_program_arguments(tmp_path, monkeypatch):
    config_file = write_config(tmp_path / ".config/lch/config.toml", {"namespace": "com.vikramsg.dotfiles"})
    monkeypatch.setenv("LCH_CONFIG_FILE", str(config_file))

    from lch.jobs import get_job_definition
    from lch.launchd import build_launch_agent_plist, get_job_paths

    job = get_job_definition("lch-screenshot-clipboard")
    paths = get_job_paths(job, home=tmp_path)
    plist = build_launch_agent_plist(
        job,
        watch_path=Path("/Users/vikramsingh/Desktop/Screenshots"),
        executable_path=Path("/Users/vikramsingh/.local/bin/lch"),
        paths=paths,
    )

    assert plist["Label"] == job.label
    assert plist["WatchPaths"] == ["/Users/vikramsingh/Desktop/Screenshots"]
    assert plist["ProgramArguments"] == ["/Users/vikramsingh/.local/bin/lch", "run", "lch-screenshot-clipboard"]
    assert plist["StandardOutPath"] == str(paths.stdout_log_path)
    assert plist["StandardErrorPath"] == str(paths.stderr_log_path)


def test_build_service_plist_has_persistent_policy_without_watch_paths(tmp_path):
    from lch.jobs import ServiceDefinition
    from lch.launchd import build_launch_agent_service_plist, get_job_paths

    service = ServiceDefinition(
        job_id="lch-opener-tunnel",
        label="com.vikramsg.dotfiles.lch-opener-tunnel",
        dispatch_command=["opener-tunnel", "run"],
    )
    paths = get_job_paths(service, home=tmp_path)

    plist = build_launch_agent_service_plist(
        service,
        executable_path=Path("/Users/vikramsingh/.local/bin/lch"),
        paths=paths,
    )

    assert plist["ProgramArguments"] == [
        "/Users/vikramsingh/.local/bin/lch",
        "run",
        "lch-opener-tunnel",
    ]
    assert plist["RunAtLoad"] is True
    assert plist["KeepAlive"] is True
    assert plist["ThrottleInterval"] == 10
    assert plist["EnvironmentVariables"] == {
        "PATH": "/Users/vikramsingh/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
    }
    assert "WatchPaths" not in plist


def test_build_watcher_plist_uses_explicit_path_and_dispatch_command(
    tmp_path, monkeypatch
):
    config_file = write_config(
        tmp_path / ".config/lch/config.toml", {"namespace": "com.vikramsg.dotfiles"}
    )
    monkeypatch.setenv("LCH_CONFIG_FILE", str(config_file))

    from lch.jobs import get_job_identity
    from lch.launchd import build_watcher_plist, get_job_paths

    job = get_job_identity("lch-example-watcher")
    paths = get_job_paths(job, home=tmp_path)
    plist = build_watcher_plist(
        job,
        watch_path=Path("/tmp/watched"),
        dispatch_command=["/usr/local/bin/example", "run", "source"],
        paths=paths,
    )

    assert plist["Label"] == "com.vikramsg.dotfiles.lch-example-watcher"
    assert plist["WatchPaths"] == ["/tmp/watched"]
    assert plist["ProgramArguments"] == [
        "/usr/local/bin/example",
        "run",
        "source",
    ]


def test_list_known_jobs_includes_installed_generic_watchers_without_duplicates(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("HOME", str(tmp_path))
    config_file = write_config(
        tmp_path / ".config/lch/config.toml", {"namespace": "com.example"}
    )
    monkeypatch.setenv("LCH_CONFIG_FILE", str(config_file))

    import lch.launchd as launchd_module

    launch_agents = tmp_path / "Library/LaunchAgents"
    launch_agents.mkdir(parents=True)
    for label in [
        "com.example.lch-screenshot-clipboard",
        "com.example.lch-example-watcher",
    ]:
        (launch_agents / f"{label}.plist").write_bytes(
            plistlib.dumps({"Label": label})
        )
    monkeypatch.setattr(
        launchd_module,
        "is_job_loaded",
        lambda label: label == "com.example.lch-example-watcher",
    )

    jobs = launchd_module.list_known_jobs()

    assert [job.job_id for job in jobs] == [
        "lch-example-watcher",
        "lch-screenshot-clipboard",
    ]
    assert jobs[0].installed is True
    assert jobs[0].loaded is True
    assert jobs[1].installed is True
    assert jobs[1].loaded is False


def test_install_status_logs_and_uninstall_commands_use_expected_paths(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    config_file = write_config(tmp_path / ".config/lch/config.toml", {"namespace": "com.vikramsg.dotfiles"})
    monkeypatch.setenv("LCH_CONFIG_FILE", str(config_file))

    import lch.cli as cli_module
    monkeypatch.setattr(cli_module.sys, "platform", "darwin")

    calls: list[list[str]] = []

    def fake_install_job(job_id: str) -> Path:
        calls.append(["install", job_id])
        return tmp_path / "Library/LaunchAgents/com.vikramsg.dotfiles.lch-screenshot-clipboard.plist"

    def fake_uninstall_job(job_id: str) -> Path:
        calls.append(["uninstall", job_id])
        return tmp_path / "Library/LaunchAgents/com.vikramsg.dotfiles.lch-screenshot-clipboard.plist"

    def fake_status_job(job_id: str) -> str:
        calls.append(["status", job_id])
        return "loaded"

    def fake_logs_job(job_id: str) -> tuple[Path, Path]:
        calls.append(["logs", job_id])
        return (
            tmp_path / "Library/Logs/com.vikramsg.dotfiles.lch-screenshot-clipboard.out.log",
            tmp_path / "Library/Logs/com.vikramsg.dotfiles.lch-screenshot-clipboard.err.log",
        )

    monkeypatch.setattr(cli_module, "install_job_launchd", fake_install_job)
    monkeypatch.setattr(cli_module, "uninstall_job_launchd", fake_uninstall_job)
    monkeypatch.setattr(cli_module, "status_job_launchd", fake_status_job)
    monkeypatch.setattr(cli_module, "logs_job_launchd", fake_logs_job)

    runner = CliRunner()

    install_result = runner.invoke(cli_module.main, ["install", "lch-screenshot-clipboard"])
    status_result = runner.invoke(cli_module.main, ["status", "lch-screenshot-clipboard"])
    logs_result = runner.invoke(cli_module.main, ["logs", "lch-screenshot-clipboard", "--paths"])
    uninstall_result = runner.invoke(cli_module.main, ["uninstall", "lch-screenshot-clipboard"])

    assert install_result.exit_code == 0
    assert status_result.exit_code == 0
    assert logs_result.exit_code == 0
    assert uninstall_result.exit_code == 0
    assert calls == [
        ["install", "lch-screenshot-clipboard"],
        ["status", "lch-screenshot-clipboard"],
        ["logs", "lch-screenshot-clipboard"],
        ["uninstall", "lch-screenshot-clipboard"],
    ]


def test_install_watcher_command_passes_explicit_contract_to_launchd(
    tmp_path, monkeypatch
):
    import lch.cli as cli_module

    monkeypatch.setattr(cli_module.sys, "platform", "darwin")
    calls: list[tuple[str, Path, list[str]]] = []

    def fake_install_watcher(
        job_id: str, *, watch_path: Path, dispatch_command: list[str]
    ) -> Path:
        calls.append((job_id, watch_path, dispatch_command))
        return tmp_path / f"{job_id}.plist"

    monkeypatch.setattr(cli_module, "install_watcher_launchd", fake_install_watcher)

    result = CliRunner().invoke(
        cli_module.main,
        [
            "install-watcher",
            "lch-example-watcher",
            "/tmp/watched path",
            "/usr/local/bin/example",
            "run",
            "source",
        ],
    )

    assert result.exit_code == 0
    assert calls == [
        (
            "lch-example-watcher",
            Path("/tmp/watched path"),
            ["/usr/local/bin/example", "run", "source"],
        )
    ]


def test_logs_command_shows_launchd_log_contents_by_default(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))

    import lch.cli as cli_module

    monkeypatch.setattr(cli_module.sys, "platform", "darwin")
    stdout_log_path = tmp_path / "Library/Logs/com.vikramsg.dotfiles.lch-example-watcher.out.log"
    stderr_log_path = tmp_path / "Library/Logs/com.vikramsg.dotfiles.lch-example-watcher.err.log"
    stdout_log_path.parent.mkdir(parents=True, exist_ok=True)
    stdout_log_path.write_text("stdout full log\n")
    stderr_log_path.write_text("stderr full log\n")
    monkeypatch.setattr(cli_module, "logs_job_launchd", lambda _job_id: (stdout_log_path, stderr_log_path))

    calls: list[list[str]] = []

    def fake_run(command: list[str], *, capture_output: bool, text: bool, check: bool) -> object:
        calls.append(command)
        assert capture_output is True
        assert text is True
        assert check is False

        class Result:
            returncode = 0
            stdout = f"tail for {command[-1]}\n"
            stderr = ""

        return Result()

    monkeypatch.setattr(cli_module.subprocess, "run", fake_run)

    runner = CliRunner()
    result = runner.invoke(cli_module.main, ["logs", "lch-example-watcher", "--lines", "50"])

    assert result.exit_code == 0
    assert "== stdout: ~/Library/Logs/com.vikramsg.dotfiles.lch-example-watcher.out.log ==\n\n" in result.output
    assert "== stderr: ~/Library/Logs/com.vikramsg.dotfiles.lch-example-watcher.err.log ==\n\n" in result.output
    assert "tail for" in result.output
    assert calls == [
        ["tail", "-n", "50", str(stdout_log_path)],
        ["tail", "-n", "50", str(stderr_log_path)],
    ]


def test_logs_command_can_follow_one_launchd_stream(tmp_path, monkeypatch):
    import lch.cli as cli_module

    monkeypatch.setattr(cli_module.sys, "platform", "darwin")
    stdout_log_path = tmp_path / "out.log"
    stderr_log_path = tmp_path / "err.log"
    monkeypatch.setattr(cli_module, "logs_job_launchd", lambda _job_id: (stdout_log_path, stderr_log_path))

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
    result = runner.invoke(cli_module.main, ["logs", "lch-example-watcher", "--follow", "--lines", "10", "--stream", "stderr"])

    assert result.exit_code == 0
    assert calls == [["tail", "-n", "10", "-F", str(stderr_log_path)]]


def test_logs_command_can_print_one_launchd_log_path(tmp_path, monkeypatch):
    import lch.cli as cli_module

    monkeypatch.setattr(cli_module.sys, "platform", "darwin")
    stdout_log_path = tmp_path / "out.log"
    stderr_log_path = tmp_path / "err.log"
    monkeypatch.setattr(cli_module, "logs_job_launchd", lambda _job_id: (stdout_log_path, stderr_log_path))

    runner = CliRunner()
    result = runner.invoke(cli_module.main, ["logs", "lch-example-watcher", "--paths", "--stream", "stderr"])

    assert result.exit_code == 0
    assert result.output.splitlines() == [str(stderr_log_path)]
