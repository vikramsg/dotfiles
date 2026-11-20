"""Which saved sessions can be reopened, and the command typed into each restored shell."""

import re
import shlex
from dataclasses import dataclass

from opencode_resume.sessions import SavedSession, is_restored, open_session
from opencode_resume.terminals import Terminal

SESSION_ID = re.compile(r"ses_[A-Za-z0-9]+")


@dataclass(frozen=True)
class Outcome:
    address: str
    session: str
    folder: str
    # The shell command to type, or None when the terminal is skipped for `reason`.
    command: str | None
    reason: str | None


def plan(
    saved: dict[str, SavedSession],
    live: dict[str, Terminal],
    boot: str,
    existing_folders: set[str],
) -> list[Outcome]:
    """One outcome per saved session that is waiting to resume."""
    outcomes = []
    open_now = {open_session(terminal, saved.get(address), boot) for address, terminal in live.items()}
    resuming: set[str] = set()
    for address, saved_session in sorted(saved.items()):
        terminal = live.get(address)
        if terminal is None or not is_restored(saved_session, terminal, boot):
            # Gone, or OpenCode is still open there: nothing waits to resume.
            continue
        reason = _skip_reason(saved_session, terminal, open_now | resuming, existing_folders)
        command = None
        if reason is None:
            resuming.add(saved_session.session)
            folder, program = shlex.quote(saved_session.folder), shlex.quote(saved_session.command)
            command = f"cd {folder} && {program} --session {saved_session.session}"
        outcomes.append(Outcome(address, saved_session.session, saved_session.folder, command, reason))
    return outcomes


def _skip_reason(
    saved: SavedSession,
    terminal: Terminal,
    open_elsewhere: set[str | None],
    existing_folders: set[str],
) -> str | None:
    if terminal.foreground is None or not terminal.foreground.is_shell:
        running = terminal.foreground.name if terminal.foreground else "something"
        return f"busy running {running}"
    if not SESSION_ID.fullmatch(saved.session):
        return f"unexpected session id {saved.session!r}"
    # A newline would press Enter in the middle of the typed command.
    if any(ord(character) < 32 for character in saved.folder + saved.command):
        return "folder or command can't be typed safely"
    if saved.folder not in existing_folders:
        return "folder no longer exists"
    if saved.session in open_elsewhere:
        return "session already open in another terminal"
    return None
