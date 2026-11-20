import json
import stat

from click.testing import CliRunner

from opencode_resume.cli import main
from opencode_resume.sessions import SavedSession, current_boot, save, track
from opencode_resume.terminals import follow_reported_sessions, read_terminals, with_reported_sessions

# A stand-in for herdr-core's `hc`: answers `ls` and `get` from terminals.json, appends every
# `send` to sent.jsonl, and fails sends to the terminals listed in unreachable.json.
FAKE_HC = """#!/usr/bin/env python3
import json, pathlib, sys
here = pathlib.Path(__file__).parent
terminals = json.loads((here / "terminals.json").read_text())
command, *rest = sys.argv[1:]
if command == "ls":
    print(json.dumps({"terminals": [
        {"address": t["address"], "state": "live", "agent": t.get("agent", "zsh")} for t in terminals
    ]}))
elif command == "get":
    print(json.dumps(next(t for t in terminals if t["address"] == rest[0])))
elif command == "events":
    print((here / "events.jsonl").read_text(), end="")
elif command == "send":
    unreachable = here / "unreachable.json"
    if unreachable.exists() and rest[0] in json.loads(unreachable.read_text()):
        sys.exit("terminal not found")
    with open(here / "sent.jsonl", "a") as sent:
        sent.write(json.dumps(rest) + "\\n")
"""


def install_fake_hc(tmp_path, monkeypatch, terminals):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    hc = bin_dir / "hc"
    hc.write_text(FAKE_HC)
    hc.chmod(hc.stat().st_mode | stat.S_IEXEC)
    (bin_dir / "terminals.json").write_text(json.dumps(terminals))
    monkeypatch.setenv("PATH", f"{bin_dir}:/usr/bin:/bin")
    return bin_dir / "sent.jsonl"


def restored_shell(address, pid, folder):
    return {"address": address, "pid": pid, "foreground": {"name": "zsh", "argv": ["zsh", "-l"], "cwd": folder}}


def test_resume_types_the_command_into_the_restored_shell(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    sent = install_fake_hc(tmp_path, monkeypatch, [restored_shell("t1", 200, str(repo))])
    state_file = tmp_path / "sessions.json"
    save(
        state_file,
        {"t1": SavedSession(boot=current_boot(), shell_pid=100, session="ses_a", folder=str(repo), command="opencode")},
    )

    result = CliRunner().invoke(main, ["--state-file", str(state_file), "resume", "--json"])

    assert result.exit_code == 0, result.output
    assert [json.loads(line) for line in sent.read_text().splitlines()] == [
        ["t1", f"cd {repo} && opencode --session ses_a"]
    ]
    assert json.loads(result.output)[0]["address"] == "t1"


def test_status_reports_without_typing_anything(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    sent = install_fake_hc(tmp_path, monkeypatch, [restored_shell("t1", 200, str(repo))])
    state_file = tmp_path / "sessions.json"
    save(
        state_file,
        {"t1": SavedSession(boot=current_boot(), shell_pid=100, session="ses_a", folder=str(repo), command="opencode")},
    )

    result = CliRunner().invoke(main, ["--state-file", str(state_file), "status"])

    assert result.exit_code == 0, result.output
    assert "would resume" in result.output
    assert not sent.exists()


def test_a_turn_seen_only_in_events_still_saves_its_session(tmp_path, monkeypatch):
    # The turn ended before the next poll: `hc get` shows an idle OpenCode with no records.
    idle_opencode = {
        "address": "t1",
        "pid": 100,
        "agent": "opencode",
        "foreground": {"name": "opencode.exe", "argv": ["opencode"], "cwd": "/repo"},
        "records": {},
    }
    install_fake_hc(tmp_path, monkeypatch, [idle_opencode])
    events = [
        {"channel": None, "seq": 1, "terminals": []},
        {"params": {"type": "status", "terminal": "t1", "data": {"records": {"ses_a": {"app": "opencode"}}}}},
        {"params": {"type": "status", "terminal": "vm-us/t2", "data": {"records": {"ses_b": {"app": "opencode"}}}}},
    ]
    (tmp_path / "bin" / "events.jsonl").write_text("".join(json.dumps(event) + "\n" for event in events))
    reported = {}

    follow_reported_sessions(lambda address, sessions: reported.update({address: sessions}))
    live, finished = read_terminals(include=set())
    live = with_reported_sessions(live, reported)

    assert track({}, live, finished, "boot-1") == {
        "t1": SavedSession(boot="boot-1", shell_pid=100, session="ses_a", folder="/repo", command="opencode")
    }


def test_a_terminal_that_cannot_be_typed_into_does_not_stop_the_others(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    sent = install_fake_hc(
        tmp_path, monkeypatch, [restored_shell("t1", 200, str(repo)), restored_shell("t2", 201, str(repo))]
    )
    (tmp_path / "bin" / "unreachable.json").write_text(json.dumps(["t1"]))
    state_file = tmp_path / "sessions.json"
    save(
        state_file,
        {
            "t1": SavedSession(
                boot=current_boot(), shell_pid=100, session="ses_a", folder=str(repo), command="opencode"
            ),
            "t2": SavedSession(
                boot=current_boot(), shell_pid=101, session="ses_b", folder=str(repo), command="opencode"
            ),
        },
    )

    result = CliRunner().invoke(main, ["--state-file", str(state_file), "resume", "--json"])

    assert result.exit_code == 0, result.output
    first, second = json.loads(result.output)
    assert first["reason"].startswith("typing failed")
    assert second["reason"] is None
    assert [json.loads(line)[0] for line in sent.read_text().splitlines()] == ["t2"]
