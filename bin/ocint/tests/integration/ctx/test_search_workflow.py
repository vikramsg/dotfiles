import inspect
import json
import sqlite3
from pathlib import Path

import pytest
from click.testing import CliRunner
from ocint.cli import main
from ocint.ctx.search import search_history
from tests.support.opencode_db import create_opencode_db


def test_search_defaults_to_primary_sessions(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _import_fixture(tmp_path, monkeypatch)
    runner = CliRunner()

    results = runner.invoke(main, ["ctx", "search", "subagent only marker", "--refresh", "off"])

    assert results.exit_code == 0, results.output
    assert results.output == "No results\n"

    subagent_results = runner.invoke(
        main, ["ctx", "search", "subagent only marker", "--include-subagents", "--refresh", "off"]
    )
    assert subagent_results.exit_code == 0, subagent_results.output
    assert "s-sub" in subagent_results.output


def test_search_help_describes_verbose_action_templates() -> None:
    # GIVEN the search command
    runner = CliRunner()

    # WHEN help is requested
    result = runner.invoke(main, ["ctx", "search", "--help"])

    # THEN verbose output is described consistently with placeholder actions
    assert result.exit_code == 0, result.output
    assert "Show citations and additional action templates." in result.output


def test_search_filters_by_file_workspace_session_since_and_terms(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _import_fixture(tmp_path, monkeypatch)

    result = CliRunner().invoke(
        main,
        [
            "ctx",
            "search",
            "native event marker",
            "--workspace",
            "repo-directory-only",
            "--file",
            "AGENTS.md",
            "--session",
            "s-primary",
            "--since",
            "30d",
            "--term",
            "related term",
            "--term",
            "error text",
            "--refresh",
            "off",
        ],
    )

    assert result.exit_code == 0, result.output
    assert "p-primary-step" in result.output
    content = " ".join(result.output.split())
    assert "Session ID s-primary" in content
    assert "Path AGENTS.md" in content


def test_search_snippet_uses_event_text_before_metadata(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _import_fixture(tmp_path, monkeypatch)

    result = CliRunner().invoke(main, ["ctx", "search", "native event marker", "--refresh", "off", "--json"])

    assert result.exit_code == 0, result.output
    snippet = json.loads(result.output)[0]["snippet"]
    assert "native event marker read AGENTS.md" in snippet
    assert "Primary ctx skill" not in snippet


def test_search_human_output_orders_content_metadata_and_shared_actions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # GIVEN an imported text result
    _import_fixture(tmp_path, monkeypatch)

    # WHEN it is rendered for a human
    result = CliRunner().invoke(main, ["ctx", "search", "long-transcript-prefix", "--refresh", "off", "--limit", "1"])

    # THEN content precedes metadata and one shared action section follows
    assert result.exit_code == 0, result.output
    content = " ".join(result.output.split())
    assert "Result 1" in result.output
    assert "Title Primary ctx skill" in content
    assert "Time 20" in content
    assert "Content type Text" in content
    assert "text · text" not in result.output
    assert "\nText\n\n" in result.output
    assert "long-transcript-prefix" in result.output
    assert "Provider opencode" in content
    assert "Event type text" in content
    assert result.output.index("Title") < result.output.index("long-transcript-prefix")
    assert result.output.index("long-transcript-prefix") < result.output.index("Metadata")
    assert result.output.count("Actions") == 1
    assert "ocint ctx show event <event-id> --window 5" in result.output
    assert "ocint ctx show session <session-id>" in result.output
    assert "Citation:" not in result.output
    assert "locate event" not in result.output


def test_search_multiple_results_have_one_shared_actions_section(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # GIVEN primary and subagent results sharing a query term
    _import_fixture(tmp_path, monkeypatch)

    # WHEN both are rendered
    result = CliRunner().invoke(
        main,
        ["ctx", "search", "marker", "--include-subagents", "--refresh", "off"],
    )

    # THEN results share exactly one final actions section
    assert result.exit_code == 0, result.output
    assert "Result 1" in result.output
    assert "Result 2" in result.output
    assert result.output.count("Actions") == 1
    assert result.output.rfind("Actions") > result.output.rfind("Metadata")


def test_search_text_content_renders_markdown(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # GIVEN text content containing Markdown structures
    monkeypatch.delenv("OPENCODE_SESSION_ID", raising=False)
    source_db = create_opencode_db(tmp_path / "opencode.db")
    with sqlite3.connect(source_db) as connection:
        connection.execute(
            "UPDATE part SET data = json_set(data, '$.text', ?) WHERE id = 'p-long-payload'",
            ("# Markdown presentation heading\n\n- first item\n- second item\n\n```python\nprint('safe')\n```",),
        )
    monkeypatch.setenv("OPENCODE_DB", str(source_db))
    monkeypatch.setenv("OCINT_CTX_DB", str(tmp_path / "ctx.sqlite"))
    runner = CliRunner()
    imported = runner.invoke(main, ["ctx", "import"])
    assert imported.exit_code == 0, imported.output

    # WHEN the Markdown text result is rendered
    result = runner.invoke(main, ["ctx", "search", "Markdown presentation heading", "--refresh", "off"])

    # THEN Markdown syntax is composed rather than emitted literally
    assert result.exit_code == 0, result.output
    assert "Markdown presentation heading" in result.output
    assert "# Markdown presentation heading" not in result.output
    assert "first item" in result.output
    assert "print('safe')" in result.output
    assert "```" not in result.output


def test_search_verbose_tool_output_includes_citation_and_locate_placeholders(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # GIVEN literal tool output
    monkeypatch.delenv("OPENCODE_SESSION_ID", raising=False)
    source_db = create_opencode_db(tmp_path / "opencode.db")
    _add_tool_fixture_row(source_db)
    monkeypatch.setenv("OPENCODE_DB", str(source_db))
    monkeypatch.setenv("OCINT_CTX_DB", str(tmp_path / "ctx.sqlite"))
    runner = CliRunner()
    imported = runner.invoke(main, ["ctx", "import"])
    assert imported.exit_code == 0, imported.output
    monkeypatch.setenv("OPENCODE_DB", str(tmp_path / "missing-opencode.db"))

    # WHEN it is rendered verbosely
    result = runner.invoke(
        main,
        ["ctx", "search", "Image read success marker", "--content", "tools", "--refresh", "off", "--verbose"],
    )

    # THEN tool Markdown-like text stays literal and verbose actions remain shared
    assert result.exit_code == 0, result.output
    content = " ".join(result.output.split())
    assert "Content type Tool output" in content
    assert "Event type tool" in content
    assert "\nTool output\n\n" in result.output
    assert "read call_TOOL_TEST completed" in result.output
    assert "/tmp/image-test.png" in result.output
    assert "Image read success marker" in result.output
    assert "# Image read success marker" in result.output
    assert "tool 0 0 0" not in result.output
    assert result.output.count("Actions") == 1
    assert "Citation opencode session=s-primary event=p-tool-read table=part" in " ".join(result.output.split())
    assert "ocint ctx locate event <event-id>" in result.output
    assert "ocint ctx locate session <session-id>" in result.output
    assert "ocint ctx locate event p-tool-read" not in result.output


def test_search_patch_output_has_explicit_content_type(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # GIVEN an imported patch result
    _import_fixture(tmp_path, monkeypatch)

    # WHEN it is rendered for a human
    result = CliRunner().invoke(main, ["ctx", "search", "file.patch normalized part marker", "--refresh", "off"])

    # THEN the primary type and raw event metadata are both explicit
    assert result.exit_code == 0, result.output
    content = " ".join(result.output.split())
    assert "Content type Patch" in content
    assert "Event type file.patch" in content
    assert "\nPatch\n\n" in result.output


def test_search_content_modes_filter_tool_events(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENCODE_SESSION_ID", raising=False)
    source_db = create_opencode_db(tmp_path / "opencode.db")
    _add_tool_fixture_row(source_db)
    monkeypatch.setenv("OPENCODE_DB", str(source_db))
    monkeypatch.setenv("OCINT_CTX_DB", str(tmp_path / "ctx.sqlite"))
    runner = CliRunner()
    imported = runner.invoke(main, ["ctx", "import"])
    assert imported.exit_code == 0, imported.output
    monkeypatch.setenv("OPENCODE_DB", str(tmp_path / "missing-opencode.db"))

    default_tool_query = runner.invoke(
        main, ["ctx", "search", "Image read success marker", "--refresh", "off", "--json"]
    )
    tools_only = runner.invoke(
        main,
        ["ctx", "search", "Image read success marker", "--content", "tools", "--refresh", "off", "--json"],
    )
    text_only = runner.invoke(
        main,
        ["ctx", "search", "native event marker", "--content", "text", "--refresh", "off", "--json"],
    )
    tools_for_text_marker = runner.invoke(
        main,
        ["ctx", "search", "native event marker", "--content", "tools", "--refresh", "off", "--json"],
    )
    all_for_text_marker = runner.invoke(
        main,
        ["ctx", "search", "native event marker", "--content", "all", "--refresh", "off", "--json"],
    )

    assert default_tool_query.exit_code == 0, default_tool_query.output
    assert default_tool_query.output == "[]\n"
    assert tools_only.exit_code == 0, tools_only.output
    assert {row["event_id"] for row in json.loads(tools_only.output)} == {"p-tool-read"}
    assert {row["event_type"] for row in json.loads(tools_only.output)} == {"tool"}
    assert text_only.exit_code == 0, text_only.output
    assert "p-primary-step" in {row["event_id"] for row in json.loads(text_only.output)}
    assert "tool" not in {row["event_type"] for row in json.loads(text_only.output)}
    assert tools_for_text_marker.exit_code == 0, tools_for_text_marker.output
    assert tools_for_text_marker.output == "[]\n"
    assert all_for_text_marker.exit_code == 0, all_for_text_marker.output
    assert "p-primary-step" in {row["event_id"] for row in json.loads(all_for_text_marker.output)}


def test_search_default_limit_is_twenty(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _import_fixture(tmp_path, monkeypatch)
    result = CliRunner().invoke(main, ["ctx", "search", "--help"])

    assert result.exit_code == 0, result.output
    assert "--limit" in result.output
    assert "default: 20" in result.output
    assert "--content" in result.output
    assert "default: text" in result.output


def test_search_file_filter_matches_all_payload_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _import_fixture(tmp_path, monkeypatch)
    runner = CliRunner()

    for file_filter in [
        "bin/ocint/ocint/ctx/search.py",
        "implementation_notes.md",
        "bin/ocint/tests/integration/ctx/test_sql_workflow.py",
    ]:
        result = runner.invoke(main, ["ctx", "search", "file.patch", "--file", file_filter, "--refresh", "off"])

        assert result.exit_code == 0, result.output
        assert "p-primary-patch" in result.output


def test_search_preserves_substring_tokens_with_opencode_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _import_fixture(tmp_path, monkeypatch)
    runner = CliRunner()

    stable_view = runner.invoke(main, ["ctx", "search", "stable view", "--refresh", "off"])
    migration = runner.invoke(main, ["ctx", "search", "migrat", "--refresh", "off"])

    assert stable_view.exit_code == 0, stable_view.output
    assert "stable views" in stable_view.output
    assert migration.exit_code == 0, migration.output
    assert "migration" in migration.output


def test_search_excludes_current_session_root_by_default_with_refresh_off(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _import_fixture(tmp_path, monkeypatch)
    monkeypatch.setenv("OPENCODE_SESSION_ID", "s-primary")

    result = CliRunner().invoke(main, ["ctx", "search", "native event marker", "--refresh", "off"])

    assert result.exit_code == 0, result.output
    assert result.output == "No results\n"
    assert "p-primary-step" not in result.output


def test_search_excludes_current_session_child_sessions_by_default_with_refresh_off(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _import_fixture(tmp_path, monkeypatch)
    monkeypatch.setenv("OPENCODE_SESSION_ID", "s-primary")

    result = CliRunner().invoke(
        main,
        ["ctx", "search", "subagent only marker", "--include-subagents", "--refresh", "off"],
    )

    assert result.exit_code == 0, result.output
    assert result.output == "No results\n"
    assert "s-sub" not in result.output


def test_search_excludes_current_session_when_root_session_row_is_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _import_fixture(tmp_path, monkeypatch)
    with sqlite3.connect(tmp_path / "ctx.sqlite") as connection:
        connection.execute("DELETE FROM ctx_session WHERE provider_session_id = 's-primary'")
    monkeypatch.setenv("OPENCODE_SESSION_ID", "s-primary")
    runner = CliRunner()

    result = runner.invoke(main, ["ctx", "search", "native event marker", "--refresh", "off"])
    included = runner.invoke(
        main,
        ["ctx", "search", "native event marker", "--include-current-session", "--refresh", "off"],
    )

    assert result.exit_code == 0, result.output
    assert result.output == "No results\n"
    assert "p-primary-step" not in result.output
    assert included.exit_code == 0, included.output
    assert "p-primary-step" in included.output


def test_search_include_current_session_opt_in_includes_active_tree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _import_fixture(tmp_path, monkeypatch)
    monkeypatch.setenv("OPENCODE_SESSION_ID", "s-primary")
    runner = CliRunner()

    root_result = runner.invoke(
        main,
        ["ctx", "search", "native event marker", "--include-current-session", "--refresh", "off"],
    )
    child_result = runner.invoke(
        main,
        [
            "ctx",
            "search",
            "subagent only marker",
            "--include-subagents",
            "--include-current-session",
            "--refresh",
            "off",
        ],
    )

    assert root_result.exit_code == 0, root_result.output
    assert "p-primary-step" in root_result.output
    assert child_result.exit_code == 0, child_result.output
    assert "s-sub" in child_result.output


def test_search_current_session_exclusion_applies_before_limit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENCODE_SESSION_ID", raising=False)
    source_db = create_opencode_db(tmp_path / "opencode.db")
    _add_current_session_limit_fixture_rows(source_db)
    monkeypatch.setenv("OPENCODE_DB", str(source_db))
    monkeypatch.setenv("OCINT_CTX_DB", str(tmp_path / "ctx.sqlite"))
    runner = CliRunner()
    imported = runner.invoke(main, ["ctx", "import"])
    assert imported.exit_code == 0, imported.output
    monkeypatch.setenv("OPENCODE_DB", str(tmp_path / "missing-opencode.db"))
    monkeypatch.setenv("OPENCODE_SESSION_ID", "s-primary")

    result = runner.invoke(
        main,
        ["ctx", "search", "current limit marker", "--refresh", "off", "--limit", "1"],
    )

    assert result.exit_code == 0, result.output
    assert "p-other-current-limit-marker" in result.output
    assert "p-active-current-limit-decoy" not in result.output


def test_search_applies_terms_before_limit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENCODE_SESSION_ID", raising=False)
    source_db = create_opencode_db(tmp_path / "opencode.db")
    _add_term_limit_fixture_rows(source_db)
    monkeypatch.setenv("OPENCODE_DB", str(source_db))
    monkeypatch.setenv("OCINT_CTX_DB", str(tmp_path / "ctx.sqlite"))
    runner = CliRunner()
    imported = runner.invoke(main, ["ctx", "import"])
    assert imported.exit_code == 0, imported.output
    monkeypatch.setenv("OPENCODE_DB", str(tmp_path / "missing-opencode.db"))

    result = runner.invoke(
        main,
        [
            "ctx",
            "search",
            "candidate window marker",
            "--term",
            "deep required term",
            "--limit",
            "1",
            "--refresh",
            "off",
        ],
    )

    assert result.exit_code == 0, result.output
    assert "p-old-required-term" in result.output


def test_search_uses_fts_as_non_authoritative_boost(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENCODE_SESSION_ID", raising=False)
    source_db = create_opencode_db(tmp_path / "opencode.db")
    _add_fts_boost_fixture_rows(source_db)
    ctx_db = tmp_path / "ctx.sqlite"
    monkeypatch.setenv("OPENCODE_DB", str(source_db))
    monkeypatch.setenv("OCINT_CTX_DB", str(ctx_db))
    runner = CliRunner()
    imported = runner.invoke(main, ["ctx", "import"])
    assert imported.exit_code == 0, imported.output
    monkeypatch.setenv("OPENCODE_DB", str(tmp_path / "missing-opencode.db"))

    _delete_ctx_fts_rows(ctx_db, ["p-fts-newer-without-boost"])
    boosted = runner.invoke(
        main,
        ["ctx", "search", "fts ranking marker", "--refresh", "off", "--limit", "1", "--json"],
    )

    assert boosted.exit_code == 0, boosted.output
    assert [row["event_id"] for row in json.loads(boosted.output)] == ["p-fts-older-with-boost"]

    _delete_ctx_fts_rows(ctx_db, ["p-fts-older-with-boost", "p-fts-newer-without-boost"])
    like_only = runner.invoke(
        main,
        ["ctx", "search", "fts ranking marker", "--refresh", "off", "--limit", "2", "--json"],
    )

    assert like_only.exit_code == 0, like_only.output
    assert {row["event_id"] for row in json.loads(like_only.output)} == {
        "p-fts-older-with-boost",
        "p-fts-newer-without-boost",
    }


def test_search_history_contract_is_explicit() -> None:
    signature = inspect.signature(search_history)

    assert list(signature.parameters) == ["request", "repository"]
    assert all(parameter.kind is not inspect.Parameter.VAR_POSITIONAL for parameter in signature.parameters.values())
    assert all(parameter.kind is not inspect.Parameter.VAR_KEYWORD for parameter in signature.parameters.values())


def _import_fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENCODE_SESSION_ID", raising=False)
    source_db = create_opencode_db(tmp_path / "opencode.db")
    monkeypatch.setenv("OPENCODE_DB", str(source_db))
    monkeypatch.setenv("OCINT_CTX_DB", str(tmp_path / "ctx.sqlite"))
    imported = CliRunner().invoke(main, ["ctx", "import"])
    assert imported.exit_code == 0, imported.output
    monkeypatch.setenv("OPENCODE_DB", str(tmp_path / "missing-opencode.db"))


def _add_current_session_limit_fixture_rows(source_db: Path) -> None:
    base_time = 2_200_000_000_000
    sessions = [
        (
            "s-other",
            None,
            "Other session",
            "/work/repo-directory-only",
            base_time - 10_000,
            base_time - 9_000,
            json.dumps({"title": "Other session"}),
        )
    ]
    rows = [
        (
            "p-other-current-limit-marker",
            "m-other-current-limit-marker",
            "s-other",
            base_time,
            base_time,
            json.dumps(
                {
                    "type": "note.created",
                    "text": "current limit marker non-active survivor",
                    "path": "current-limit-other.txt",
                }
            ),
        )
    ]
    rows.extend(
        (
            f"p-active-current-limit-decoy-{index:03d}",
            "m-primary",
            "s-primary",
            base_time + 1_000 + index,
            base_time + 1_000 + index,
            json.dumps(
                {
                    "type": "note.created",
                    "text": "current limit marker active-session decoy",
                    "path": f"current-limit-decoy-{index:03d}.txt",
                }
            ),
        )
        for index in range(5)
    )
    with sqlite3.connect(source_db) as connection:
        connection.executemany(
            """
            INSERT INTO session (id, parent_id, title, directory, time_created, time_updated, data)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            sessions,
        )
        connection.executemany("INSERT INTO part VALUES (?, ?, ?, ?, ?, ?)", rows)


def _add_term_limit_fixture_rows(source_db: Path) -> None:
    base_time = 2_000_000_000_000
    rows = [
        (
            "p-old-required-term",
            "m-primary",
            "s-primary",
            base_time,
            base_time,
            json.dumps(
                {
                    "type": "note.created",
                    "text": "candidate window marker deep required term",
                    "path": "term-limit-valid.txt",
                }
            ),
        )
    ]
    rows.extend(
        (
            f"p-new-decoy-{index:03d}",
            "m-primary",
            "s-primary",
            base_time + 1_000 + index,
            base_time + 1_000 + index,
            json.dumps(
                {
                    "type": "note.created",
                    "text": "candidate window marker decoy text",
                    "path": f"term-limit-decoy-{index:03d}.txt",
                }
            ),
        )
        for index in range(105)
    )
    with sqlite3.connect(source_db) as connection:
        connection.executemany("INSERT INTO part VALUES (?, ?, ?, ?, ?, ?)", rows)


def _add_fts_boost_fixture_rows(source_db: Path) -> None:
    base_time = 2_100_000_000_000
    rows = [
        (
            "p-fts-older-with-boost",
            "m-primary",
            "s-primary",
            base_time,
            base_time,
            json.dumps(
                {
                    "type": "note.created",
                    "text": "fts ranking marker older indexed event",
                    "path": "fts-boost-older.txt",
                }
            ),
        ),
        (
            "p-fts-newer-without-boost",
            "m-primary",
            "s-primary",
            base_time + 1_000,
            base_time + 1_000,
            json.dumps(
                {
                    "type": "note.created",
                    "text": "fts ranking marker newer like-only event",
                    "path": "fts-boost-newer.txt",
                }
            ),
        ),
    ]
    with sqlite3.connect(source_db) as connection:
        connection.executemany("INSERT INTO part VALUES (?, ?, ?, ?, ?, ?)", rows)


def _add_tool_fixture_row(source_db: Path) -> None:
    with sqlite3.connect(source_db) as connection:
        timestamp = int(connection.execute("SELECT MAX(timeCreated) + 1 FROM part").fetchone()[0] or 1)
        connection.execute(
            "INSERT INTO part VALUES (?, ?, ?, ?, ?, ?)",
            (
                "p-tool-read",
                "m-primary",
                "s-primary",
                timestamp,
                timestamp,
                json.dumps(
                    {
                        "type": "tool",
                        "tool": "read",
                        "callID": "call_TOOL_TEST",
                        "status": "completed",
                        "path": "/tmp/image-test.png",
                        "output": "# Image read success marker",
                        "tokens": {"input": 0, "output": 0, "reasoning": 0},
                    }
                ),
            ),
        )


def _delete_ctx_fts_rows(ctx_db: Path, event_ids: list[str]) -> None:
    placeholders = ", ".join("?" for _ in event_ids)
    with sqlite3.connect(ctx_db) as connection:
        connection.execute(f"DELETE FROM ctx_event_fts WHERE event_id IN ({placeholders})", event_ids)
