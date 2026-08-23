import socket
import subprocess
import threading

import pytest

from opener_tunnel.server import UnixSocketServer


def send_request(socket_path, payload: bytes) -> None:
    client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        client.connect(str(socket_path))
        client.sendall(payload)
    finally:
        client.close()


def test_valid_url_reaches_configured_browser_command(tmp_path):
    calls: list[tuple[list[str], bool]] = []

    def fake_run(command: list[str], *, check: bool):
        calls.append((command, check))
        return subprocess.CompletedProcess(command, 0)

    socket_path = tmp_path / "opener.sock"
    server = UnixSocketServer(
        socket_path,
        ["browser", "--new-window"],
        run_command=fake_run,
    )
    server.start()
    thread = threading.Thread(target=server.accept_once, kwargs={"timeout": 2})
    thread.start()

    send_request(socket_path, b"https://example.com/path?q=1\n")
    thread.join(timeout=3)
    server.close()

    assert not thread.is_alive()
    assert calls == [
        (["browser", "--new-window", "https://example.com/path?q=1"], True)
    ]
    assert not socket_path.exists()


@pytest.mark.parametrize("url", ["file:///tmp/a", "javascript:alert(1)", "not-a-url"])
def test_rejects_non_http_urls(tmp_path, url):
    calls: list[list[str]] = []

    def fake_run(command: list[str], *, check: bool):
        calls.append(command)
        return subprocess.CompletedProcess(command, 0)

    socket_path = tmp_path / "opener.sock"
    server = UnixSocketServer(socket_path, ["browser"], run_command=fake_run)
    server.start()
    thread = threading.Thread(target=server.accept_once, kwargs={"timeout": 2})
    thread.start()

    send_request(socket_path, f"{url}\n".encode())
    thread.join(timeout=3)
    server.close()

    assert calls == []


def test_cleanup_preserves_replacement_path(tmp_path):
    socket_path = tmp_path / "opener.sock"
    server = UnixSocketServer(socket_path, ["browser"])
    server.start()

    socket_path.unlink()
    socket_path.write_text("not the owned socket")
    server.close()

    assert socket_path.read_text() == "not the owned socket"
