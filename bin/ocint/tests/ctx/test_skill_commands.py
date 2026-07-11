from collections.abc import Sequence
from pathlib import Path

import pytest
from click.testing import CliRunner, Result
from ocint.cli import main
from tests.fixtures.opencode_db import create_opencode_db


def test_skill_command_suite_reads_imported_index(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENCODE_SESSION_ID", raising=False)
    source_db = create_opencode_db(tmp_path / "opencode.db")
    monkeypatch.setenv("OPENCODE_DB", str(source_db))
    monkeypatch.setenv("OCINT_CTX_DB", str(tmp_path / "ctx.sqlite"))
    runner = CliRunner()

    imported = runner.invoke(main, ["ctx", "import"])
    assert imported.exit_code == 0, imported.output
    monkeypatch.setenv("OPENCODE_DB", str(tmp_path / "missing-opencode.db"))

    checks: list[tuple[Sequence[str], str]] = [
        (["ctx", "status"], "SESSIONS: 2"),
        (["ctx", "status", "--json"], '"sessions": 2'),
        (["ctx", "sources"], "OpenCode DB"),
        (["ctx", "sources", "--json"], '"source_type": "sqlite"'),
        (["ctx", "search", "native event marker", "--refresh", "off"], "p-primary-step"),
        (["ctx", "search", "native event marker", "--refresh", "off"], "p-primary-step"),
        (["ctx", "search", "stable view", "--refresh", "off"], "stable views"),
        (["ctx", "search", "migrat", "--refresh", "off"], "migration"),
        (
            ["ctx", "search", "native event marker", "--workspace", "/work/repo-directory-only", "--refresh", "off"],
            "p-primary-step",
        ),
        (["ctx", "search", "native event marker", "--file", "AGENTS.md", "--refresh", "off"], "p-primary-step"),
        (["ctx", "search", "native event marker", "--since", "30d", "--refresh", "off"], "p-primary-step"),
        (
            [
                "ctx",
                "search",
                "native event marker",
                "--term",
                "related term",
                "--term",
                "error text",
                "--refresh",
                "off",
            ],
            "p-primary-step",
        ),
        (["ctx", "search", "native event marker", "--session", "s-primary", "--refresh", "off"], "p-primary-step"),
        (["ctx", "search", "native event marker", "--verbose", "--refresh", "off"], "Citation"),
        (["ctx", "search", "subagent only marker", "--include-subagents", "--refresh", "off"], "s-sub"),
        (
            ["ctx", "search", "native event marker", "--include-current-session", "--refresh", "off"],
            "p-primary-step",
        ),
        (["ctx", "show", "event", "p-primary-step", "--window", "5"], "p-primary-step"),
        (["ctx", "show", "event", "p-primary-step", "--window", "0", "--json"], '"event_id": "p-primary-step"'),
        (["ctx", "show", "session", "s-primary"], "SESSION: s-primary"),
        (["ctx", "locate", "event", "p-primary-step"], "p-primary-step"),
        (["ctx", "locate", "event", "p-primary-step", "--json"], '"kind": "event"'),
        (["ctx", "locate", "session", "s-primary"], "s-primary"),
        (["ctx", "locate", "session", "s-primary", "--json"], '"kind": "session"'),
        (["ctx", "docs", "show", "sql"], "ctx_sessions"),
        (["ctx", "docs", "search", "stable views"], "stable views"),
        (["ctx", "sql", "SELECT provider, COUNT(*) AS sessions FROM ctx_sessions GROUP BY provider"], "opencode"),
        (
            [
                "ctx",
                "sql",
                "SELECT event_type, COUNT(*) AS events FROM ctx_events GROUP BY event_type ORDER BY events DESC",
            ],
            "step-finish",
        ),
        (["ctx", "sql", "SELECT path, provider, provider_session_id FROM ctx_files_touched LIMIT 20"], "opencode"),
        (
            [
                "ctx",
                "sql",
                "SELECT path, provider, provider_session_id FROM ctx_files_touched WHERE path LIKE '%AGENTS.md%' LIMIT 20",
            ],
            "AGENTS.md",
        ),
        (["ctx", "sql", "SELECT provider, source_type, name, sessions, events FROM ctx_sources"], "OpenCode DB"),
    ]
    for args, expected in checks:
        result = runner.invoke(main, list(args))
        _assert_contains(result, expected)

    for args, out_path in [
        (
            ["ctx", "show", "session", "s-primary", "--mode", "lite", "--out", str(tmp_path / "lite.txt")],
            tmp_path / "lite.txt",
        ),
        (
            ["ctx", "show", "session", "s-primary", "--mode", "full", "--out", str(tmp_path / "full.txt")],
            tmp_path / "full.txt",
        ),
        (
            ["ctx", "show", "session", "s-primary", "--format", "markdown", "--out", str(tmp_path / "session.md")],
            tmp_path / "session.md",
        ),
    ]:
        result = runner.invoke(main, list(args))
        _assert_contains(result, "Wrote")
        assert out_path.read_text().strip()


def _assert_contains(result: Result, expected: str) -> None:
    assert result.exit_code == 0, result.output
    assert result.output.strip()
    assert " ".join(expected.split()) in " ".join(result.output.split())
