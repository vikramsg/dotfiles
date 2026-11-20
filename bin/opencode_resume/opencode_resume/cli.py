"""`watch` keeps the saved sessions current; `status` and `resume` act on them after a restart."""

import json
import sys
import threading
import time
from dataclasses import asdict
from pathlib import Path

import click

from opencode_resume import resume as resume_plan
from opencode_resume import sessions, terminals


@click.group()
@click.option(
    "--state-file",
    type=click.Path(path_type=Path),
    default=sessions.default_state_file,
    show_default="$XDG_STATE_HOME/opencode-resume/sessions.json",
    help="Where the sessions are saved.",
)
@click.pass_context
def main(context: click.Context, state_file: Path) -> None:
    """Reopen OpenCode sessions in Herdr terminals that herdr-core restored after a restart."""
    context.obj = state_file


@main.command()
@click.option("--interval", type=click.FloatRange(min=1), default=5.0, show_default=True, help="Seconds between looks.")
@click.pass_obj
def watch(state_file: Path, interval: float) -> None:
    """Save the session each terminal's OpenCode has open (the lch service)."""
    saved = sessions.load(state_file)
    boot = sessions.current_boot()
    reported: dict[str, tuple[str, ...]] = {}
    lock = threading.Lock()

    def remember(address: str, sessions_reported: tuple[str, ...]) -> None:
        with lock:
            reported[address] = sessions_reported

    def follow() -> None:
        while True:
            try:
                terminals.follow_reported_sessions(remember)
            except (terminals.HcError, ValueError) as error:
                print(error, file=sys.stderr, flush=True)
            time.sleep(interval)

    threading.Thread(target=follow, daemon=True).start()
    while True:
        try:
            live = terminals.live_terminals(include=set(saved))
        except terminals.HcError as error:
            # Keep what is saved: herdr-core may not be up yet after a reboot.
            print(error, file=sys.stderr, flush=True)
        else:
            with lock:
                live = terminals.with_reported_sessions(live, reported)
                reported.clear()
            tracked = sessions.track(saved, live, boot)
            if tracked != saved:
                sessions.save(state_file, tracked)
                saved = tracked
        time.sleep(interval)


@main.command()
@click.option("--json", "as_json", is_flag=True, help="Print the outcomes as JSON.")
@click.pass_obj
def status(state_file: Path, as_json: bool) -> None:
    """Show what `resume` would do, without typing anything."""
    _report(_plan(state_file), as_json, done="would resume")


@main.command()
@click.option("--json", "as_json", is_flag=True, help="Print the outcomes as JSON.")
@click.pass_obj
def resume(state_file: Path, as_json: bool) -> None:
    """Type the resume command into each restored terminal that had OpenCode open."""
    outcomes = _plan(state_file)
    for outcome in outcomes:
        if outcome.command:
            terminals.send(outcome.address, outcome.command)
    _report(outcomes, as_json, done="resumed")


def _plan(state_file: Path) -> list[resume_plan.Outcome]:
    saved = sessions.load(state_file)
    try:
        live = terminals.live_terminals(include=set(saved))
    except terminals.HcError as error:
        raise click.ClickException(str(error)) from error
    return resume_plan.plan(saved, live, sessions.current_boot())


def _report(outcomes: list[resume_plan.Outcome], as_json: bool, done: str) -> None:
    if as_json:
        click.echo(json.dumps([asdict(outcome) for outcome in outcomes]))
        return
    if not outcomes:
        click.echo("No OpenCode sessions to resume.")
    for outcome in outcomes:
        click.echo(f"{outcome.address}\t{outcome.reason or done}\t{outcome.session}\t{outcome.folder}")
