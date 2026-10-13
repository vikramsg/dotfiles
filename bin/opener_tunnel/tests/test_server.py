import socket
import subprocess
import threading

import pytest

from opener_tunnel.server import UnixSocketServer


def send_request(socket_path, payload: bytes) -> bytes:
    client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        client.connect(str(socket_path))
        client.sendall(payload)
        client.settimeout(3)
        return client.recv(8192)
    finally:
        client.close()


def test_valid_url_reaches_configured_browser_command(socket_directory):
    calls: list[tuple[list[str], bool]] = []

    def fake_run(command: list[str], *, check: bool, timeout: float):
        calls.append((command, check))
        return subprocess.CompletedProcess(command, 0)

    socket_path = socket_directory / "opener.sock"
    server = UnixSocketServer(
        socket_path,
        ["browser", "--new-window"],
        run_command=fake_run,
    )
    server.start()
    thread = threading.Thread(target=server.accept_once, kwargs={"timeout": 2})
    thread.start()

    response = send_request(socket_path, b"https://example.com/path?q=1\n")
    thread.join(timeout=3)
    server.close()

    assert not thread.is_alive()
    assert response == b"OK\n"
    assert calls == [
        (["browser", "--new-window", "https://example.com/path?q=1"], True)
    ]
    assert not socket_path.exists()


@pytest.mark.parametrize("url", ["file:///tmp/a", "javascript:alert(1)", "not-a-url"])
def test_rejects_non_http_urls(socket_directory, url):
    calls: list[list[str]] = []

    def fake_run(command: list[str], **kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(command, 0)

    socket_path = socket_directory / "opener.sock"
    server = UnixSocketServer(socket_path, ["browser"], run_command=fake_run)
    server.start()
    thread = threading.Thread(target=server.accept_once, kwargs={"timeout": 2})
    thread.start()

    response = send_request(socket_path, f"{url}\n".encode())
    thread.join(timeout=3)
    server.close()

    assert calls == []
    assert response.startswith(b"ERROR: ")


def test_url_arriving_after_poll_interval_is_opened(socket_directory, monkeypatch):
    import opener_tunnel.server as server_module

    calls = []
    reading_request = threading.Event()
    read_url = server_module._read_url

    def signal_request_read(connection, *, timeout):
        reading_request.set()
        return read_url(connection, timeout=timeout)

    monkeypatch.setattr(server_module, "_read_url", signal_request_read)

    def fake_run(command, **kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(command, 0)

    server = UnixSocketServer(socket_directory / "s", ["browser"], run_command=fake_run)
    server.start()
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.connect(str(server.socket_path))
        thread = threading.Thread(target=server.accept_once, kwargs={"timeout": 0.01})
        thread.start()
        assert reading_request.wait(timeout=2)
        threading.Event().wait(0.1)
        client.sendall(b"https://example.com/delayed\n")
        client.settimeout(2)
        assert client.recv(100) == b"OK\n"
        thread.join(timeout=2)
    server.close()
    assert calls == [["browser", "https://example.com/delayed"]]


@pytest.mark.parametrize(
    "failure",
    [
        subprocess.CalledProcessError(1, "browser"),
        subprocess.TimeoutExpired("browser", 5),
    ],
)
def test_browser_failure_is_reported(socket_directory, failure):
    def fake_run(command, **kwargs):
        raise failure

    server = UnixSocketServer(socket_directory / "s", ["browser"], run_command=fake_run)
    server.start()
    thread = threading.Thread(target=server.accept_once, kwargs={"timeout": 2})
    thread.start()
    response = send_request(server.socket_path, b"https://example.com/\n")
    thread.join(timeout=3)
    server.close()
    assert response == b"ERROR: browser command failed\n"


def test_incomplete_request_expires_and_next_request_succeeds(socket_directory):
    calls = []

    def fake_run(command, **kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(command, 0)

    server = UnixSocketServer(
        socket_directory / "s", ["browser"], run_command=fake_run, request_timeout=0.1
    )
    server.start()
    for payload, expected in [
        (b"https://example.com/incomplete", b"ERROR:"),
        (b"https://example.com/complete\n", b"OK\n"),
    ]:
        thread = threading.Thread(target=server.accept_once, kwargs={"timeout": 2})
        thread.start()
        assert send_request(server.socket_path, payload).startswith(expected)
        thread.join(timeout=3)
    server.close()
    assert calls == [["browser", "https://example.com/complete"]]


def test_cleanup_preserves_replacement_path(socket_directory):
    socket_path = socket_directory / "opener.sock"
    server = UnixSocketServer(socket_path, ["browser"])
    server.start()

    socket_path.unlink()
    socket_path.write_text("not the owned socket")
    server.close()

    assert socket_path.read_text() == "not the owned socket"
