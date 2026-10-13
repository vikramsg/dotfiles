import os
from pathlib import Path
import socket
import subprocess
import threading

import pytest


WRAPPER = Path(__file__).resolve().parents[2] / "xdg-open"


@pytest.fixture
def wrapper_environment(socket_directory):
    # Run the Linux branch on macOS with a socket-backed netcat test double.
    nc = socket_directory / "nc"
    nc.write_text(
        "#!/usr/bin/env python3\n"
        "import socket, sys\n"
        "s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)\n"
        "s.settimeout(0.1)\n"
        "s.connect(sys.argv[-1])\n"
        "s.sendall(sys.stdin.buffer.read())\n"
        "try:\n"
        " while data := s.recv(8192): sys.stdout.buffer.write(data)\n"
        "except TimeoutError: pass\n"
    )
    nc.chmod(0o755)
    return {
        **os.environ,
        "HOME": str(socket_directory),
        "OSTYPE": "linux-gnu",
        "PATH": f"{socket_directory}:{os.environ['PATH']}",
    }


@pytest.mark.parametrize(
    "reply,success",
    [
        (b"OK\n", True),
        (b"ERROR: browser command failed\n", False),
        (b"", False),
        (b"unexpected\n", False),
        (None, False),
    ],
)
def test_wrapper_requires_explicit_browser_success(
    socket_directory, wrapper_environment, reply, success
):
    received = []
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    listener.bind(str(socket_directory / ".opener.sock"))
    listener.listen()

    def respond():
        with listener.accept()[0] as connection:
            received.append(connection.recv(8192))
            if reply is None:
                threading.Event().wait(0.2)
            else:
                connection.sendall(reply)

    thread = threading.Thread(target=respond)
    thread.start()
    result = subprocess.run(
        ["bash", str(WRAPPER), "https://example.com/pr"],
        env=wrapper_environment,
        capture_output=True,
        text=True,
        timeout=3,
    )
    thread.join(timeout=3)
    listener.close()
    assert (result.returncode == 0) is success
    assert received == [b"https://example.com/pr\n"]
    if not success:
        assert result.stderr


def test_wrapper_fails_when_socket_is_missing(wrapper_environment):
    result = subprocess.run(
        ["bash", str(WRAPPER), "https://example.com/"],
        env=wrapper_environment,
        capture_output=True,
        text=True,
        timeout=3,
    )
    assert result.returncode != 0


def test_wrapper_fails_when_socket_has_no_listener(
    socket_directory, wrapper_environment
):
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    listener.bind(str(socket_directory / ".opener.sock"))
    listener.close()
    result = subprocess.run(
        ["bash", str(WRAPPER), "https://example.com/"],
        env=wrapper_environment,
        capture_output=True,
        text=True,
        timeout=3,
    )
    assert result.returncode != 0
