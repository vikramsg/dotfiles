import logging
import shlex
import signal
import subprocess
import threading
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager

from opener_tunnel.server import UnixSocketServer


LOGGER = logging.getLogger(__name__)


class TmuxController:
    def __init__(
        self,
        session_name: str,
        tmux_command: Sequence[str],
        process_command: Sequence[str],
        *,
        run_command: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    ) -> None:
        self.session_name = session_name
        self.tmux_command = list(tmux_command)
        self.process_command = list(process_command)
        self.run_command = run_command
        self.session_id: str | None = None

    def start(self) -> None:
        if self._session_exists(f"={self.session_name}"):
            raise RuntimeError(
                f"tmux session {self.session_name!r} already exists; refusing ownership"
            )
        pane_command = "exec " + shlex.join(self.process_command)
        result = self.run_command(
            [
                *self.tmux_command,
                "new-session",
                "-d",
                "-P",
                "-F",
                "#{session_id}",
                "-s",
                self.session_name,
                pane_command,
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        self.session_id = result.stdout.strip()
        if not self.session_id:
            raise RuntimeError("tmux did not return the created session ID")
        LOGGER.info("tmux session created")

    def exists(self) -> bool:
        return self.session_id is not None and self._session_exists(self.session_id)

    def cleanup(self) -> None:
        if self.session_id is None:
            return
        self.run_command(
            [*self.tmux_command, "kill-session", "-t", self.session_id],
            capture_output=True,
            text=True,
            check=False,
        )
        self.session_id = None

    def _session_exists(self, target: str) -> bool:
        result = self.run_command(
            [*self.tmux_command, "has-session", "-t", target],
            capture_output=True,
            text=True,
            check=False,
        )
        return result.returncode == 0


class Supervisor:
    def __init__(
        self,
        server: UnixSocketServer,
        tmux: TmuxController,
        stop_event: threading.Event,
        *,
        poll_interval: float = 0.25,
    ) -> None:
        self.server = server
        self.tmux = tmux
        self.stop_event = stop_event
        self.poll_interval = poll_interval

    def run(self) -> int:
        try:
            self.server.start()
            LOGGER.info("socket listener started")
            self.tmux.start()
            while not self.stop_event.is_set():
                if not self.tmux.exists():
                    LOGGER.warning("tmux session disappeared")
                    return 1
                self.server.accept_once(timeout=self.poll_interval)
            return 0
        finally:
            LOGGER.info("cleanup started")
            self.tmux.cleanup()
            self.server.close()
            LOGGER.info("cleanup completed")


@contextmanager
def stop_on_signals(stop_event: threading.Event) -> Iterator[None]:
    previous_handlers: dict[signal.Signals, signal.Handlers] = {}

    def request_stop(_signum: int, _frame: object) -> None:
        stop_event.set()

    for signal_number in (signal.SIGINT, signal.SIGTERM):
        previous_handlers[signal_number] = signal.signal(signal_number, request_stop)
    try:
        yield
    finally:
        for signal_number, handler in previous_handlers.items():
            signal.signal(signal_number, handler)
