from click.testing import CliRunner


def test_run_job_dispatches_to_screenshot_clipboard_event(monkeypatch):
    import lch.cli as cli_module

    dispatched: list[str] = []

    def fake_run_job(job_id: str) -> None:
        dispatched.append(job_id)

    monkeypatch.setattr(cli_module, "run_job", fake_run_job)

    runner = CliRunner()
    result = runner.invoke(cli_module.main, ["run", "lch-screenshot-clipboard"])

    assert result.exit_code == 0
    assert dispatched == ["lch-screenshot-clipboard"]


def test_run_job_invokes_expected_screenshot_command(monkeypatch):
    import lch.launchd as launchd_module

    called: list[list[str]] = []

    def fake_run(command: list[str], *, check: bool) -> None:
        assert check is True
        called.append(command)

    monkeypatch.setattr(launchd_module.subprocess, "run", fake_run)

    launchd_module.run_job("lch-screenshot-clipboard")

    assert called[0][-2:] == ["clipboard", "on-event"]
    assert called[0][0].endswith("screenshot")


def test_run_job_prefers_installed_tool_path_for_launchd_style_environments(tmp_path, monkeypatch):
    import lch.launchd as launchd_module

    home = tmp_path / "home"
    screenshot_executable = home / ".local/bin/screenshot"
    screenshot_executable.parent.mkdir(parents=True, exist_ok=True)
    screenshot_executable.write_text("#!/bin/sh\nexit 0\n")
    screenshot_executable.chmod(0o755)
    monkeypatch.setenv("HOME", str(home))

    called: list[list[str]] = []

    def fake_run(command: list[str], *, check: bool) -> None:
        assert check is True
        called.append(command)

    monkeypatch.setattr(launchd_module.subprocess, "run", fake_run)

    launchd_module.run_job("lch-screenshot-clipboard")

    assert called == [[str(screenshot_executable), "clipboard", "on-event"]]


def test_run_sync_job_invokes_expected_screenshot_command(monkeypatch):
    import lch.launchd as launchd_module

    called: list[list[str]] = []

    def fake_run(command: list[str], *, check: bool) -> None:
        assert check is True
        called.append(command)

    monkeypatch.setattr(launchd_module.subprocess, "run", fake_run)

    launchd_module.run_job("lch-screenshot-sync")

    assert called[0][-2:] == ["sync", "run"]
    assert called[0][0].endswith("screenshot")


def test_configured_service_dispatch_uses_exec(tmp_path, monkeypatch):
    home = tmp_path / "home"
    opener_tunnel_executable = home / ".local/bin/opener-tunnel"
    opener_tunnel_executable.parent.mkdir(parents=True)
    opener_tunnel_executable.write_text("#!/bin/sh\nexit 0\n")
    opener_tunnel_executable.chmod(0o755)
    config_file = tmp_path / "config.toml"
    config_file.write_text(
        """
namespace = "com.example"

[services.lch-opener-tunnel]
command = ["opener-tunnel", "run"]
""".strip()
        + "\n"
    )
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("LCH_CONFIG_FILE", str(config_file))
    import lch.launchd as launchd_module

    calls: list[tuple[str, list[str]]] = []

    def fake_execvp(executable: str, command: list[str]) -> None:
        calls.append((executable, command))

    monkeypatch.setattr(launchd_module.os, "execvp", fake_execvp)

    launchd_module.run_job("lch-opener-tunnel")

    assert calls == [
        (str(opener_tunnel_executable), [str(opener_tunnel_executable), "run"])
    ]
