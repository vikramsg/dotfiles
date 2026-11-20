"""This machine's herdr-core terminals, read and typed into through the `hc` CLI."""

import json
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

SHELLS = frozenset({"zsh", "bash", "sh", "fish", "dash", "ksh"})


class HcError(RuntimeError):
    """`hc` failed or isn't reachable, for example while herdr-core is still starting."""


@dataclass(frozen=True)
class Foreground:
    """The program a terminal's shell is running in front, or the shell itself when idle."""

    name: str
    argv: tuple[str, ...]
    folder: str

    @property
    def is_opencode(self) -> bool:
        program = Path(self.argv[0]).name if self.argv else self.name
        return program.startswith("opencode")

    @property
    def is_shell(self) -> bool:
        # A login shell reports itself as `-zsh`.
        return self.name.lstrip("-") in SHELLS

    @property
    def session_argument(self) -> str | None:
        """The session OpenCode was started on with `--session <id>` or `-s <id>`."""
        for index, argument in enumerate(self.argv):
            if argument.startswith("--session="):
                return argument.removeprefix("--session=")
            if argument in ("--session", "-s") and index + 1 < len(self.argv):
                return self.argv[index + 1]
        return None


@dataclass(frozen=True)
class Terminal:
    """A live terminal. `shell_pid` changes when herdr-core restores the terminal after a restart."""

    address: str
    shell_pid: int
    foreground: Foreground | None
    # Sessions herdr-core lists for OpenCode in this terminal. OpenCode reports one only while it
    # works on a turn; herdr-core drops it once OpenCode is idle.
    reported_sessions: tuple[str, ...]

    @property
    def runs_opencode(self) -> bool:
        return self.foreground is not None and self.foreground.is_opencode

    def has_session_open(self, session: str) -> bool:
        if not self.runs_opencode or self.foreground is None:
            return False
        return session in self.reported_sessions or self.foreground.session_argument == session

    @classmethod
    def from_hc(cls, data: dict[str, Any]) -> Terminal:
        foreground = data.get("foreground")
        return cls(
            address=data["address"],
            shell_pid=data["pid"],
            foreground=Foreground(
                name=foreground.get("name") or "",
                argv=tuple(foreground.get("argv") or ()),
                folder=foreground.get("cwd") or "",
            )
            if foreground
            else None,
            reported_sessions=opencode_sessions(data.get("records")),
        )


def opencode_sessions(records: dict[str, Any] | None) -> tuple[str, ...]:
    """The OpenCode sessions in a terminal's `records`, from `hc get` or a status event."""
    return tuple(session for session, record in (records or {}).items() if (record or {}).get("app") == "opencode")


def hc_executable() -> str:
    # herdr-core installs hc in ~/.local/bin, which lch's systemd units leave off PATH.
    return shutil.which("hc") or str(Path.home() / ".local/bin/hc")


def run_hc(*arguments: str) -> str:
    try:
        result = subprocess.run([hc_executable(), *arguments], capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise HcError(f"hc {' '.join(arguments)}: {error}") from error
    if result.returncode != 0:
        raise HcError(f"hc {' '.join(arguments)}: {result.stderr.strip() or f'exit {result.returncode}'}")
    return result.stdout


def live_terminals(include: set[str]) -> dict[str, Terminal]:
    """This machine's live terminals running OpenCode, plus the live ones among `include`.

    `hc ls` also lists other machines' terminals (`vm-us/t3`); each machine's own copy of this
    tool handles those.
    """
    listed = json.loads(run_hc("ls", "--json"))["terminals"]
    wanted = [
        entry["address"]
        for entry in listed
        if "/" not in entry["address"]
        and entry.get("state") == "live"
        and (entry.get("agent") == "opencode" or entry["address"] in include)
    ]
    terminals = {}
    for address in wanted:
        terminal = Terminal.from_hc(json.loads(run_hc("get", address, "--json")))
        terminals[terminal.address] = terminal
    return terminals


def follow_reported_sessions(on_report: Callable[[str, tuple[str, ...]], None]) -> None:
    """Call `on_report(address, sessions)` each time a local OpenCode reports its sessions.

    OpenCode reports a session only while it works on a turn, which can last under a second, so
    polling `hc get` misses short turns; `hc events` streams every report. Returns when the stream
    ends (herdr-core stopped); raises HcError when it can't start.
    """
    try:
        events = subprocess.Popen([hc_executable(), "events", "--json"], stdout=subprocess.PIPE, text=True)
    except OSError as error:
        raise HcError(f"hc events: {error}") from error
    assert events.stdout is not None
    with events:
        for line in events.stdout:
            event = json.loads(line).get("params") or {}
            address = event.get("terminal") or ""
            if event.get("type") != "status" or "/" in address:
                continue
            sessions = opencode_sessions((event.get("data") or {}).get("records"))
            if sessions:
                on_report(address, sessions)


def with_reported_sessions(live: dict[str, Terminal], reported: dict[str, tuple[str, ...]]) -> dict[str, Terminal]:
    """`live`, with sessions seen in events for OpenCode terminals that `hc get` shows none for."""
    return {
        address: replace(terminal, reported_sessions=reported[address])
        if address in reported and terminal.runs_opencode and not terminal.reported_sessions
        else terminal
        for address, terminal in live.items()
    }


def send(address: str, text: str) -> None:
    """Paste `text` into the terminal and press Enter."""
    run_hc("send", address, text)
