import shutil
import subprocess
import threading
import uuid

import pytest

from opener_tunnel.supervisor import Supervisor, TmuxController


class FakeServer:
    def __init__(self) -> None:
        self.started = False
        self.closed = False

    def start(self) -> None:
        self.started = True

    def accept_once(self, *, timeout: float) -> bool:
        assert timeout > 0
        return False

    def close(self) -> None:
        self.closed = True


class FakeTmux:
    def __init__(self) -> None:
        self.states = iter([True, False])
        self.started = False
        self.cleaned = False

    def start(self) -> None:
        self.started = True

    def exists(self) -> bool:
        return next(self.states)

    def cleanup(self) -> None:
        self.cleaned = True


def test_session_disappearance_makes_supervisor_exit_and_cleanup():
    server = FakeServer()
    tmux = FakeTmux()

    result = Supervisor(server, tmux, threading.Event()).run()

    assert result == 1
    assert server.started and server.closed
    assert tmux.started and tmux.cleaned


def test_stop_request_cleans_owned_resources():
    server = FakeServer()
    tmux = FakeTmux()
    stop_event = threading.Event()
    stop_event.set()

    result = Supervisor(server, tmux, stop_event).run()

    assert result == 0
    assert server.started and server.closed
    assert tmux.started and tmux.cleaned


def test_tmux_uses_configured_argv_and_records_created_id():
    calls: list[list[str]] = []

    def fake_run(command: list[str], **kwargs):
        calls.append(command)
        if "has-session" in command:
            return subprocess.CompletedProcess(command, 1, stdout="", stderr="")
        if "new-session" in command:
            return subprocess.CompletedProcess(command, 0, stdout="$9\n", stderr="")
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    tmux = TmuxController(
        "configured-session",
        ["tmux", "-L", "configured-server"],
        ["process", "--flag", "value with spaces"],
        run_command=fake_run,
    )

    tmux.start()
    tmux.cleanup()

    assert calls[1] == [
        "tmux",
        "-L",
        "configured-server",
        "new-session",
        "-d",
        "-P",
        "-F",
        "#{session_id}",
        "-s",
        "configured-session",
        "exec process --flag 'value with spaces'",
    ]
    assert calls[2] == [
        "tmux",
        "-L",
        "configured-server",
        "kill-session",
        "-t",
        "$9",
    ]


def test_tmux_refuses_preexisting_named_session():
    def fake_run(command: list[str], **kwargs):
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    tmux = TmuxController("existing", ["tmux"], ["process"], run_command=fake_run)

    with pytest.raises(RuntimeError, match="refusing ownership"):
        tmux.start()
    assert tmux.session_id is None


@pytest.mark.skipif(shutil.which("tmux") is None, reason="tmux is unavailable")
def test_isolated_tmux_session_ends_when_fake_process_exits(tmp_path):
    tmux_executable = shutil.which("tmux")
    assert tmux_executable is not None
    server_name = f"opener-test-{uuid.uuid4().hex}"
    session_name = f"opener-test-{uuid.uuid4().hex}"
    fake_process = tmp_path / "fake-process"
    fake_process.write_text("#!/bin/sh\nexit 0\n")
    fake_process.chmod(0o755)
    controller = TmuxController(
        session_name,
        [tmux_executable, "-L", server_name, "-f", "/dev/null"],
        [str(fake_process)],
    )

    try:
        controller.start()
        for _attempt in range(100):
            if not controller.exists():
                break
            threading.Event().wait(0.01)
        assert not controller.exists()
    finally:
        controller.cleanup()
