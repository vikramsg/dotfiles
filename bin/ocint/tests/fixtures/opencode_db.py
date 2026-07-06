import json
import sqlite3
import time
from pathlib import Path


def create_opencode_db(path: Path) -> Path:
    con = sqlite3.connect(path)
    con.executescript(
        """
        CREATE TABLE session (
          id TEXT PRIMARY KEY,
          parentID TEXT,
          title TEXT,
          directory TEXT,
          timeCreated INTEGER,
          timeUpdated INTEGER,
          data TEXT NOT NULL
        );
        CREATE TABLE message (
          id TEXT PRIMARY KEY,
          sessionID TEXT,
          timeCreated INTEGER,
          data TEXT NOT NULL
        );
        CREATE TABLE session_message (
          session_id TEXT NOT NULL,
          message_id TEXT NOT NULL
        );
        CREATE TABLE part (
          id TEXT PRIMARY KEY,
          messageID TEXT NOT NULL,
          sessionID TEXT NOT NULL,
          timeCreated INTEGER NOT NULL,
          timeUpdated INTEGER NOT NULL,
          data TEXT NOT NULL
        );
        CREATE TABLE event (
          id TEXT PRIMARY KEY,
          aggregate_id TEXT,
          seq INTEGER NOT NULL,
          type TEXT NOT NULL,
          data TEXT NOT NULL
        );
        CREATE TABLE project (
          id TEXT PRIMARY KEY,
          path TEXT,
          data TEXT NOT NULL
        );
        CREATE TABLE workspace (
          id TEXT PRIMARY KEY,
          path TEXT,
          data TEXT NOT NULL
        );
        CREATE TABLE account (
          id TEXT PRIMARY KEY,
          provider TEXT NOT NULL,
          data TEXT NOT NULL
        );
        """
    )
    now = int(time.time() * 1000) - 86_400_000
    long_text = " ".join(["long-transcript-prefix"] * 30) + " IMPORTANT_LATE_MARKER full transcript content"
    con.executemany(
        "INSERT INTO session VALUES (?, ?, ?, ?, ?, ?, ?)",
        [
            (
                "s-primary",
                None,
                "Primary ctx skill",
                "/work/repo-directory-only",
                now,
                now + 10,
                json.dumps({"title": "Primary ctx skill"}),
            ),
            (
                "s-sub",
                "s-primary",
                "Subagent implementation",
                "/work/repo-directory-only",
                now + 20,
                now + 30,
                json.dumps({"title": "Subagent implementation"}),
            ),
        ],
    )
    con.executemany(
        "INSERT INTO message VALUES (?, ?, ?, ?)",
        [
            (
                "m-primary",
                "s-primary",
                now + 1,
                json.dumps(
                    {
                        "role": "assistant",
                        "providerID": "anthropic",
                        "modelID": "claude-sonnet-4-5",
                        "text": "ctx skill migration decision",
                    }
                ),
            ),
            (
                "m-sub",
                "s-sub",
                now + 21,
                json.dumps(
                    {
                        "role": "assistant",
                        "providerID": "openai",
                        "modelID": "gpt-5.5",
                        "text": "subagent ctx skill implementation detail",
                    }
                ),
            ),
        ],
    )
    con.executemany("INSERT INTO session_message VALUES (?, ?)", [("s-primary", "m-primary"), ("s-sub", "m-sub")])
    con.executemany(
        "INSERT INTO part VALUES (?, ?, ?, ?, ?, ?)",
        [
            (
                "p-primary-step",
                "m-primary",
                "s-primary",
                now + 2,
                now + 2,
                json.dumps(
                    {
                        "type": "step-finish",
                        "cost": 1.25,
                        "tokens": {"input": 10, "output": 20, "reasoning": 3, "cache": {"read": 4, "write": 5}},
                        "path": "AGENTS.md",
                        "text": "stable views for ctx skill",
                    }
                ),
            ),
            (
                "p-sub-step",
                "m-sub",
                "s-sub",
                now + 22,
                now + 22,
                json.dumps(
                    {
                        "type": "step-finish",
                        "cost": 2.5,
                        "tokens": {"input": 1, "output": 2, "total": 9},
                        "path": "bin/ocint/ocint/ctx/search.py",
                        "text": "subagent only marker",
                    }
                ),
            ),
            (
                "p-non-usage",
                "m-primary",
                "s-primary",
                now + 3,
                now + 3,
                json.dumps({"type": "text", "cost": 100, "tokens": {"input": 999}}),
            ),
        ],
    )
    con.executemany(
        "INSERT INTO event VALUES (?, ?, ?, ?, ?)",
        [
            (
                "evt_native_tool",
                "s-primary",
                1,
                "tool.invocation",
                json.dumps(
                    {
                        "sessionID": "s-primary",
                        "timestamp": now + 4,
                        "text": "native event marker read AGENTS.md for stable views related term error text",
                        "path": "AGENTS.md",
                    }
                ),
            ),
            (
                "evt_native_patch",
                "s-primary",
                2,
                "file.patch",
                json.dumps(
                    {
                        "sessionID": "s-primary",
                        "timestamp": now + 5,
                        "patch": {
                            "files": ["bin/ocint/ocint/ctx/search.py", "implementation_notes.md"],
                            "metadata": {
                                "filePath": "bin/ocint/tests/ctx/test_sql.py",
                                "relativePath": "bin/ocint/ocint/opencode/schema.py",
                            },
                        },
                    }
                ),
            ),
            (
                "evt_json_session",
                None,
                3,
                "note.created",
                json.dumps(
                    {
                        "sessionID": "s-primary",
                        "timestamp": now + 6,
                        "message": "json session fallback native event marker",
                        "filePaths": ["README.md", "justfile"],
                    }
                ),
            ),
            (
                "evt_long_payload",
                "s-primary",
                4,
                "note.long",
                json.dumps(
                    {"sessionID": "s-primary", "timestamp": now + 7, "text": long_text, "path": "long-transcript.txt"}
                ),
            ),
            (
                "evt_sub",
                "s-sub",
                5,
                "note.created",
                json.dumps(
                    {
                        "sessionID": "s-sub",
                        "timestamp": now + 24,
                        "text": "subagent only marker",
                        "path": "subagent.txt",
                    }
                ),
            ),
        ],
    )
    con.execute(
        "INSERT INTO project VALUES (?, ?, ?)", ("project-dotfiles", "/work/dotfiles", json.dumps({"name": "dotfiles"}))
    )
    con.execute(
        "INSERT INTO workspace VALUES (?, ?, ?)",
        ("workspace-dotfiles", "/work/dotfiles", json.dumps({"name": "dotfiles"})),
    )
    con.execute(
        "INSERT INTO account VALUES (?, ?, ?)",
        ("acct-local", "opencode", json.dumps({"token": "redacted-test-fixture"})),
    )
    con.commit()
    con.close()
    return path
