import logging
import socket
import stat
import subprocess
from collections.abc import Callable, Sequence
from pathlib import Path
from urllib.parse import urlsplit


MAX_REQUEST_BYTES = 8192
LOGGER = logging.getLogger(__name__)


class InvalidRequest(ValueError):
    """Raised when a socket message is not a valid browser request."""


class UnixSocketServer:
    def __init__(
        self,
        socket_path: Path,
        browser_command: Sequence[str],
        *,
        run_command: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    ) -> None:
        self.socket_path = socket_path
        self.browser_command = list(browser_command)
        self.run_command = run_command
        self._listener: socket.socket | None = None
        self._owned_identity: tuple[int, int] | None = None

    def start(self) -> None:
        listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            listener.bind(str(self.socket_path))
            socket_stat = self.socket_path.lstat()
        except BaseException:
            listener.close()
            raise
        self._listener = listener
        self._owned_identity = (socket_stat.st_dev, socket_stat.st_ino)
        try:
            listener.listen()
        except BaseException:
            self.close()
            raise

    def accept_once(self, *, timeout: float) -> bool:
        if self._listener is None:
            raise RuntimeError("socket listener is not started")
        self._listener.settimeout(timeout)
        try:
            connection, _address = self._listener.accept()
        except socket.timeout:
            return False

        with connection:
            connection.settimeout(timeout)
            try:
                url = _read_url(connection)
                self.run_command([*self.browser_command, url], check=True)
            except (InvalidRequest, OSError) as exc:
                LOGGER.warning("browser request rejected: %s", exc)
            except subprocess.SubprocessError:
                LOGGER.error("browser request rejected: browser command failed")
            else:
                LOGGER.info("browser request accepted")
        return True

    def close(self) -> None:
        if self._listener is not None:
            self._listener.close()
            self._listener = None

        owned_identity = self._owned_identity
        self._owned_identity = None
        if owned_identity is None:
            return
        try:
            socket_stat = self.socket_path.lstat()
        except FileNotFoundError:
            return
        if (
            socket_stat.st_dev,
            socket_stat.st_ino,
        ) == owned_identity and stat.S_ISSOCK(socket_stat.st_mode):
            self.socket_path.unlink()


def _read_url(connection: socket.socket) -> str:
    payload = bytearray()
    while b"\n" not in payload and len(payload) <= MAX_REQUEST_BYTES:
        chunk = connection.recv(min(4096, MAX_REQUEST_BYTES + 1 - len(payload)))
        if not chunk:
            break
        payload.extend(chunk)
    if len(payload) > MAX_REQUEST_BYTES:
        raise InvalidRequest("request is too large")

    message, separator, remainder = bytes(payload).partition(b"\n")
    if not separator:
        raise InvalidRequest("request must end with a newline")
    if remainder:
        raise InvalidRequest("request must contain one URL")
    try:
        url = message.removesuffix(b"\r").decode("utf-8")
        parsed = urlsplit(url)
        if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
            raise InvalidRequest("only http and https URLs with a host are allowed")
    except (UnicodeError, ValueError) as exc:
        raise InvalidRequest("URL is malformed") from exc
    return url
