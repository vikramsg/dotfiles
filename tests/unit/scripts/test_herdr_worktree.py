import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parents[3] / "skills" / "herdr" / "scripts" / "worktree"

# A stand-in for `hc`: the herdr-app document and the terminals live in a JSON file.
STUB_HC = r"""
import json, os, sys

STATE = os.environ["HC_STUB_STATE"]
state = json.load(open(STATE))
args = sys.argv[1:]
state["calls"].append({"argv": args, "session": os.environ.get("HC_SESSION")})


def save():
    json.dump(state, open(STATE, "w"))


def not_found(address):
    save()
    print(json.dumps({"error": {"kind": "not_found", "message": f"no terminal {address!r}"}}), file=sys.stderr)
    sys.exit(3)


if args[0] == "connect":
    for line in filter(str.strip, sys.stdin):
        call = json.loads(line)
        method, params = call["method"], call["params"]
        if method == "hello":
            reply = {"result": {}}
        elif method == "doc.get":
            reply = {"result": {"value": state["doc"], "version": state["version"]}}
        elif state["conflicts"] or params["version"] != state["version"]:
            if state["conflicts"]:
                state["conflicts"] -= 1
                state["doc"]["spaces"].append(state.pop("other_write"))
                state["version"] += 1
            reply = {"error": {"code": "version_conflict"}}
        else:
            state["doc"], state["version"] = params["value"], state["version"] + 1
            reply = {"result": {"version": state["version"]}}
        print(json.dumps({"jsonrpc": "2.0", "id": call["id"], **reply}))
elif args[0] == "run":
    address = f"t{len(state['terminals']) + 100}"
    state["terminals"][address] = "live"
    print(json.dumps({"address": address}))
elif args[0] == "kill":
    if args[1] not in state["terminals"]:
        not_found(args[1])
    state["terminals"][args[1]] = "finished"
elif args[0] == "rm":
    if args[1] not in state["terminals"]:
        not_found(args[1])
    del state["terminals"][args[1]]
save()
"""


def block(terminal: str) -> dict:
    return {"id": f"p-{terminal}", "type": "block", "content": {"terminal": terminal}, "size": {"weight": 1.0}}


def make_space(space_id: str, folder: str, *tabs: list[str]) -> dict:
    """A space whose tabs nest their terminals in a row holding a column, like the app writes."""
    return {
        "folder": folder,
        "id": space_id,
        "name": "",
        "tabs": [
            {
                "id": f"tb-{space_id}-{i}",
                "name": "",
                "root": {
                    "id": f"tb-{space_id}-{i}",
                    "type": "row",
                    "children": [block(terminals[0]), {"id": f"s-{space_id}-{i}", "type": "column", "children": [block(t) for t in terminals[1:]]}],
                },
            }
            for i, terminals in enumerate(tabs)
        ],
    }


class Env:
    def __init__(self, tmp_path: Path) -> None:
        self.home = tmp_path / "home"
        self.home.mkdir()
        self.state_file = tmp_path / "hc-state.json"
        hc = tmp_path / "hc"
        hc.write_text(f"#!{sys.executable}\n{STUB_HC}")
        hc.chmod(0o755)
        self.env = {
            "PATH": os.environ["PATH"],
            "HOME": str(self.home),
            "HC_BIN": str(hc),
            "HC_STUB_STATE": str(self.state_file),
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@example.com",
            "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@example.com",
        }

        origin = tmp_path / "origin.git"
        seed = tmp_path / "seed"
        self.git(tmp_path, "init", "--quiet", "--bare", "-b", "main", str(origin))
        self.git(tmp_path, "init", "--quiet", "-b", "main", str(seed))
        (seed / "README").write_text("hi\n")
        self.git(seed, "add", "README")
        self.git(seed, "commit", "--quiet", "-m", "seed")
        self.git(seed, "push", "--quiet", str(origin), "main")
        self.repo = tmp_path / "src" / "app"
        self.git(tmp_path, "clone", "--quiet", str(origin), str(self.repo))
        self.worktrees = self.home / ".herdr" / "worktrees" / "app"
        self.write_state({"spaces": []})

    def git(self, cwd: Path, *args: str) -> str:
        return subprocess.run(["git", *args], cwd=cwd, env=self.env, check=True, capture_output=True, text=True).stdout

    def write_state(self, doc: object, terminals: dict | None = None, conflicts: int = 0, other_write: dict | None = None) -> None:
        state = {"doc": doc, "version": 7, "conflicts": conflicts, "terminals": terminals or {}, "calls": []}
        if other_write:
            state["other_write"] = other_write
        self.state_file.write_text(json.dumps(state))

    def state(self) -> dict:
        return json.loads(self.state_file.read_text())

    def worktree(self, *args: str, cwd: Path | None = None, **env: str) -> subprocess.CompletedProcess:
        return subprocess.run([str(SCRIPT), *args], cwd=cwd or self.repo, env={**self.env, **env}, capture_output=True, text=True, check=False)

    def add_worktree(self, branch: str) -> Path:
        path = self.worktrees / branch
        self.git(self.repo, "worktree", "add", "--quiet", "-b", branch, str(path))
        return path


@pytest.fixture
def env(tmp_path: Path) -> Env:
    return Env(tmp_path)


def mutating_calls(state: dict) -> list[list[str]]:
    return [c["argv"] for c in state["calls"] if c["argv"][0] in ("kill", "rm", "run")]


def test_new_then_remove_round_trip(env: Env) -> None:
    sibling = make_space("sp-other", "/elsewhere", ["t1", "t2"])
    env.write_state({"spaces": [sibling]}, terminals={"t1": "live", "t2": "live"})

    made = env.worktree("new", "feature/x", "--session", "friday")
    assert made.returncode == 0, made.stderr
    opened = json.loads(made.stdout)
    path = env.worktrees / "feature-x"
    assert opened["path"] == str(path) and path.is_dir()
    assert opened["session"] == "friday"
    state = env.state()
    assert [s["folder"] for s in state["doc"]["spaces"]] == ["/elsewhere", str(path)]
    added = state["doc"]["spaces"][1]
    assert {c["session"] for c in state["calls"]} == {"friday"}

    removed = env.worktree("remove", "feature/x", "--session", "friday")
    assert removed.returncode == 0, removed.stderr
    assert json.loads(removed.stdout) == {
        "path": str(path),
        "session": "friday",
        "git_worktree_removed": True,
        "spaces": [added["id"]],
        "terminals": [opened["opencode"], opened["shell"]],
        "errors": [],
    }
    assert not path.exists()
    assert env.git(env.repo, "branch", "--list", "feature/x").strip() == "feature/x"
    state = env.state()
    assert state["doc"] == {"spaces": [sibling]}
    assert state["terminals"] == {"t1": "live", "t2": "live"}


def test_dirty_worktree_is_refused_without_force(env: Env) -> None:
    path = env.add_worktree("dirty")
    (path / "scratch.txt").write_text("unsaved\n")
    doc = {"spaces": [make_space("sp-dirty", str(path), ["t1"])]}
    env.write_state(doc, terminals={"t1": "live"})

    refused = env.worktree("remove", "dirty")
    assert refused.returncode == 1
    assert "git worktree remove" in refused.stderr
    assert path.is_dir()
    state = env.state()
    assert state["doc"] == doc and state["version"] == 7
    assert mutating_calls(state) == []

    forced = env.worktree("remove", "dirty", "--force")
    assert forced.returncode == 0, forced.stderr
    assert not path.exists()
    assert json.loads(forced.stdout)["terminals"] == ["t1"]
    assert env.state()["doc"] == {"spaces": []}


def test_deleted_folder_still_removes_space_and_terminals(env: Env) -> None:
    path = env.worktrees / "gone"
    doc = {"spaces": [make_space("sp-gone", str(path), ["t1"], ["t2", "t3"])]}
    env.write_state(doc, terminals={"t1": "live", "t2": "live"})  # t3 is already gone

    r = env.worktree("remove", "gone")
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    assert out["git_worktree_removed"] is False
    assert out["spaces"] == ["sp-gone"]
    assert out["terminals"] == ["t1", "t2", "t3"]
    assert out["errors"] == []
    state = env.state()
    assert state["doc"] == {"spaces": []}
    assert state["terminals"] == {}


def test_version_conflict_is_retried_and_keeps_the_other_write(env: Env) -> None:
    path = env.add_worktree("busy")
    other = make_space("sp-new", "/new", ["t9"])
    env.write_state({"spaces": [make_space("sp-busy", str(path), ["t1"])]}, terminals={"t1": "live", "t9": "live"}, conflicts=1, other_write=other)

    r = env.worktree("remove", "busy")
    assert r.returncode == 0, r.stderr
    state = env.state()
    assert state["doc"] == {"spaces": [other]}
    assert state["terminals"] == {"t9": "live"}
    assert sum(c["argv"][0] == "connect" for c in state["calls"]) == 5  # read, set (lost), read, set, plus the first read


@pytest.mark.parametrize(
    "doc",
    [
        ["not", "a", "dict"],
        {"spaces": {"sp": {}}},
        {"spaces": [{"id": "sp-x", "folder": "/x", "tabs": [{"id": "tb", "root": {"id": "n", "type": "browser", "url": "x"}}]}]},
        {"spaces": [{"id": "sp-x", "folder": "/x", "tabs": [{"id": "tb", "root": {"id": "n", "type": "block", "content": {"web": "x"}}}]}]},
    ],
)
def test_unknown_doc_shape_changes_nothing(env: Env, doc: object) -> None:
    path = env.add_worktree("shape")
    env.write_state(doc, terminals={"t1": "live"})

    r = env.worktree("remove", "shape")
    assert r.returncode == 1
    assert "format may have changed" in r.stderr
    assert path.is_dir()
    state = env.state()
    assert state["doc"] == doc and state["version"] == 7
    assert mutating_calls(state) == []


def test_siblings_extra_keys_and_shared_terminals_are_untouched(env: Env) -> None:
    path = env.add_worktree("mine")
    first = make_space("sp-a", "/a", ["t1", "shared"])
    last = make_space("sp-b", "/b", ["t4"])
    doc = {
        "activeSpaceId": "sp-a",
        "spaces": [first, make_space("sp-mine", str(path) + "/", ["t2", "shared"]), make_space("sp-mine-2", str(path), ["t3"]), last],
    }
    live = {t: "live" for t in ("t1", "shared", "t2", "t3", "t4")}
    env.write_state(doc, terminals=live)

    r = env.worktree("remove", "mine")
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    assert out["spaces"] == ["sp-mine", "sp-mine-2"]
    assert out["terminals"] == ["t2", "t3"]
    state = env.state()
    assert state["doc"] == {"activeSpaceId": "sp-a", "spaces": [first, last]}
    assert state["terminals"] == {"t1": "live", "shared": "live", "t4": "live"}


def test_refuses_from_a_terminal_in_the_space(env: Env) -> None:
    path = env.add_worktree("self")
    doc = {"spaces": [make_space("sp-self", str(path), ["t1", "t2"])]}
    env.write_state(doc, terminals={"t1": "live", "t2": "live"})

    r = env.worktree("remove", "self", HC_TERMINAL_ID="t2")
    assert r.returncode == 1
    assert "t2" in r.stderr
    assert path.is_dir()
    assert env.state()["doc"] == doc
    assert mutating_calls(env.state()) == []


def test_refuses_from_inside_the_worktree(env: Env) -> None:
    path = env.add_worktree("here")
    (path / "sub").mkdir()
    env.write_state({"spaces": [make_space("sp-here", str(path), ["t1"])]}, terminals={"t1": "live"})

    r = env.worktree("remove", "here", "--repo", str(env.repo), cwd=path / "sub")
    assert r.returncode == 1
    assert "current directory" in r.stderr
    assert path.is_dir()
    assert mutating_calls(env.state()) == []


def test_nothing_to_remove(env: Env) -> None:
    r = env.worktree("remove", "never")
    assert r.returncode == 1
    assert "no worktree folder or space" in r.stderr
