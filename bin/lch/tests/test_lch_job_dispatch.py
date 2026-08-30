import os
import plistlib
import signal
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest
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


def test_macos_application_launches_with_lch_logs(tmp_path, monkeypatch):
    import lch.launchd as launchd_module

    app = tmp_path / "Example.app"
    executable = app / "Contents/MacOS/Example"
    executable.parent.mkdir(parents=True)
    executable.write_text("")
    (app / "Contents/Info.plist").write_bytes(
        plistlib.dumps({"CFBundleExecutable": "Example"})
    )
    paths = launchd_module.JobPaths(
        plist_path=tmp_path / "agent.plist",
        stdout_log_path=tmp_path / "stdout.log",
        stderr_log_path=tmp_path / "stderr.log",
    )
    calls: list[list[str]] = []
    stopped: list[Path] = []

    class CompletedProcess:
        args: list[str]

        def __init__(self, arguments: list[str]) -> None:
            self.args = arguments

        def poll(self) -> int:
            return 0

        def wait(self) -> int:
            return 0

    def fake_popen(arguments: list[str]) -> CompletedProcess:
        calls.append(arguments)
        return CompletedProcess(arguments)

    monkeypatch.setattr(launchd_module.sys, "platform", "darwin")
    monkeypatch.setattr(launchd_module.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(
        launchd_module,
        "stop_application",
        lambda path: stopped.append(path),
    )

    launchd_module.run_macos_application(app, paths=paths)

    assert calls == [[
        "/usr/bin/open",
        "-W",
        "-g",
        "--stdout",
        str(paths.stdout_log_path),
        "--stderr",
        str(paths.stderr_log_path),
        str(app),
    ]]
    assert stopped == [executable]


@pytest.mark.skipif(sys.platform != "darwin", reason="requires macOS process tools")
def test_application_termination_stops_exact_native_executable(tmp_path):
    import lch.launchd as launchd_module

    executable = tmp_path / "Example Script"
    shutil.copyfile("/bin/sleep", executable)
    executable.chmod(0o755)
    subprocess.run(["/usr/bin/codesign", "--force", "--sign", "-", str(executable)], check=True)
    process = subprocess.Popen([str(executable), "10"])
    try:
        time.sleep(0.1)
        assert process.poll() is None
        launchd_module.stop_application(executable, timeout=2)
        assert process.poll() is not None
    finally:
        if process.poll() is None:
            os.kill(process.pid, signal.SIGKILL)
            process.wait()


@pytest.mark.skipif(sys.platform != "darwin", reason="requires macOS process tools")
def test_application_termination_ignores_path_split_across_arguments(tmp_path):
    import lch.launchd as launchd_module

    executable = tmp_path / "Example App"
    process = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(10)", str(executable)]
    )
    try:
        time.sleep(0.1)
        launchd_module.stop_application(executable, timeout=0.2)
        assert process.poll() is None
    finally:
        process.terminate()
        process.wait()


def test_linux_application_dispatch_reports_not_implemented(tmp_path, monkeypatch):
    config_file = tmp_path / "config.toml"
    config_file.write_text(
        """
namespace = "com.example"

[services.example.application]
type = "linux"
path = "/example.desktop"
""".strip()
        + "\n"
    )
    monkeypatch.setenv("LCH_CONFIG_FILE", str(config_file))

    from lch.launchd import run_job

    with pytest.raises(RuntimeError, match="Linux application services are not implemented"):
        run_job("example")
