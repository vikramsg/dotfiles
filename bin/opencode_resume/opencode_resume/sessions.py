"""The OpenCode session each terminal had open, kept on disk across restarts."""

import json
import os
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path

from opencode_resume.terminals import Terminal


@dataclass(frozen=True)
class SavedSession:
    """What a terminal's OpenCode had open, and under which shell process."""

    # A shell is identified by its pid and the machine's boot: pids start over after a reboot,
    # so a restored shell can get the pid the old one had.
    boot: str
    shell_pid: int
    session: str
    folder: str
    # The program as OpenCode was started (`opencode`, `opencode2`, a full path).
    command: str


def current_boot() -> str:
    """An id that changes with every boot of this machine."""
    try:
        return Path("/proc/sys/kernel/random/boot_id").read_text().strip()
    except FileNotFoundError:
        # macOS: `{ sec = 1793974716, usec = 779830 } Fri Nov  6 15:18:36 2026`.
        return subprocess.run(
            ["/usr/sbin/sysctl", "-n", "kern.boottime"], capture_output=True, text=True, check=True
        ).stdout.strip()


def is_restored(saved: SavedSession, terminal: Terminal, boot: str) -> bool:
    """herdr-core gave the terminal a new shell since the session was saved."""
    return saved.boot != boot or saved.shell_pid != terminal.shell_pid


def default_state_file() -> Path:
    state = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local/state")
    return state / "opencode-resume" / "sessions.json"


def load(path: Path) -> dict[str, SavedSession]:
    try:
        data = json.loads(path.read_text())
    except FileNotFoundError:
        return {}
    return {address: SavedSession(**saved) for address, saved in data["terminals"].items()}


def save(path: Path, saved: dict[str, SavedSession]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_suffix(".tmp")
    partial.write_text(json.dumps({"terminals": {address: asdict(s) for address, s in saved.items()}}, indent=2))
    partial.replace(path)


def track(saved: dict[str, SavedSession], live: dict[str, Terminal], boot: str) -> dict[str, SavedSession]:
    """The sessions to keep after one look at the live terminals.

    | Terminal now                                  | Kept                                  |
    | --------------------------------------------- | ------------------------------------- |
    | runs OpenCode on a known session              | that session, under this shell        |
    | runs OpenCode, session not known yet          | nothing (a new OpenCode replaces it)  |
    | restored after a restart (new shell or boot)  | the saved session, waiting to resume  |
    | same shell, OpenCode gone                     | nothing: the user quit OpenCode       |
    | finished or gone                              | nothing                               |
    """
    tracked = {}
    for address, terminal in live.items():
        previous = saved.get(address)
        if terminal.runs_opencode and terminal.foreground is not None:
            session = _open_session(terminal, previous, boot)
            if session:
                tracked[address] = SavedSession(
                    boot=boot,
                    shell_pid=terminal.shell_pid,
                    session=session,
                    folder=terminal.foreground.folder,
                    command=terminal.foreground.argv[0] if terminal.foreground.argv else "opencode",
                )
        elif previous and is_restored(previous, terminal, boot):
            tracked[address] = previous
    return tracked


def _open_session(terminal: Terminal, previous: SavedSession | None, boot: str) -> str | None:
    reported = terminal.reported_sessions
    if len(reported) == 1:
        return reported[0]
    # More than one reported session gives no way to tell which one the TUI shows; keep the
    # one already saved if it is among them.
    if previous and previous.session in reported:
        return previous.session
    if terminal.foreground is not None and terminal.foreground.session_argument:
        return terminal.foreground.session_argument
    # Idle OpenCode reports nothing; the session saved under this same shell is still open.
    if previous and not is_restored(previous, terminal, boot):
        return previous.session
    return None
