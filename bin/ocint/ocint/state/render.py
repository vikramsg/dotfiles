from collections.abc import Mapping, Sequence

from ocint._models import ResolvedPaths
from ocint._timeutil import UsageWindow
from ocint.presentation import Presentation, Text, data_table, document, key_value_section
from ocint.state.models import StateDetailed, StateSessionUsage, StateSummary, UsageTokens


def render_config(paths: ResolvedPaths) -> Presentation:
    return document(
        "OpenCode paths",
        key_value_section(
            "Resolved paths",
            [
                ("Config", paths.config_path),
                ("Config exists", _yes_no(paths.config_exists)),
                ("Database", paths.db_path),
                ("Database exists", _yes_no(paths.db_exists)),
            ],
        ),
    )


def render_schema(rows: Sequence[Mapping[str, object]]) -> Presentation:
    return document(
        "OpenCode database schema",
        data_table(
            "Columns",
            ("Table", "Column", "Type", "Primary key"),
            (
                (
                    row.get("table_name"),
                    row.get("column_name"),
                    row.get("column_type"),
                    _yes_no(bool(row.get("primary_key"))),
                )
                for row in rows
            ),
        ),
    )


def render_summary(summary: StateSummary, window: UsageWindow) -> Presentation:
    return document(
        "OpenCode usage summary",
        key_value_section(
            "Usage",
            [
                ("Database", summary.db_path),
                ("Window", window.label),
                ("Sessions", _format_int(summary.sessions)),
                ("Messages", _format_int(summary.messages)),
                ("Cost", _format_cost(summary.cost)),
            ],
        ),
        key_value_section("Tokens", _token_rows(summary.tokens)),
    )


def render_detailed(detailed: StateDetailed, window: UsageWindow) -> Presentation:
    return document(
        "Detailed OpenCode usage",
        key_value_section(
            "Summary",
            [
                ("Database", detailed.db_path),
                ("Window", window.label),
                ("OpenCode total cost", _format_cost(detailed.opencode_total_cost)),
                ("Message-attributed cost", _format_cost(detailed.message_attributed_cost)),
            ],
        ),
        Text(_detailed_note(window), style="dim"),
        Text(""),
        data_table(
            "By project",
            ("Project", "Cost"),
            ((_source_label(row.worktree), _format_cost(row.cost)) for row in detailed.projects if row.cost != 0),
        ),
        data_table(
            "By agent",
            ("Agent", "Cost"),
            ((f"{row.agent} ({row.kind})", _format_cost(row.cost)) for row in detailed.agents if row.cost != 0),
        ),
        data_table(
            "By project / agent",
            ("Project / agent", "Cost"),
            _project_agent_rows(detailed),
        ),
    )


def render_sessions(sessions: Sequence[StateSessionUsage], window: UsageWindow) -> Presentation:
    return document(
        "OpenCode session usage",
        key_value_section("Selection", [("Window", window.label), ("Sessions", _format_int(len(sessions)))]),
        data_table(
            "Sessions",
            ("Session", "Usage"),
            (
                (
                    "\n".join(
                        [
                            session.session_id,
                            f"First: {session.first_seen.isoformat()}",
                            f"Last: {session.last_seen.isoformat()}",
                        ]
                    ),
                    "\n".join(
                        [
                            f"Messages: {_format_int(session.messages)}",
                            f"Cost: {_format_cost(session.cost)}",
                            _format_tokens(session.tokens),
                        ]
                    ),
                )
                for session in sessions
            ),
        ),
    )


def render_query(rows: Sequence[Mapping[str, object]]) -> Presentation:
    if not rows:
        return document("OpenCode query results", data_table("Rows", (), ()))
    columns = tuple(rows[0])
    return document(
        "OpenCode query results",
        data_table(
            "Rows",
            columns,
            (tuple(row.get(column) for column in columns) for row in rows),
        ),
    )


def _token_rows(tokens: UsageTokens) -> list[tuple[str, object]]:
    return [
        ("Input", _format_int(tokens.input)),
        ("Output", _format_int(tokens.output)),
        ("Reasoning", _format_int(tokens.reasoning)),
        ("Cache read", _format_int(tokens.cache_read)),
        ("Cache write", _format_int(tokens.cache_write)),
        ("Total", _format_int(tokens.total)),
    ]


def _project_agent_rows(detailed: StateDetailed) -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []
    for project in detailed.projects:
        project_rows = [
            row
            for row in detailed.project_agents
            if row.project_id == project.project_id and row.worktree == project.worktree and row.cost != 0
        ]
        if not project_rows:
            continue
        if rows:
            rows.append(("", ""))
        rows.extend(
            (f"{_source_label(row.worktree)}: {row.agent} ({row.kind})", _format_cost(row.cost)) for row in project_rows
        )
    return rows


def _format_tokens(tokens: UsageTokens) -> str:
    return "\n".join(f"{label}: {value}" for label, value in _token_rows(tokens))


def _format_int(value: int) -> str:
    return f"{value:,}"


def _format_cost(value: float) -> str:
    return f"{value:.6f}"


def _detailed_note(window: UsageWindow) -> str:
    if window.start_ms is None:
        return "Note: Detailed uses assistant-message costs; Summary uses session aggregates, so totals may differ."
    return (
        "Note: Detailed counts assistant messages created in this window. "
        "Summary counts the lifetime cost of sessions updated in this window, so totals may differ."
    )


def _source_label(value: str | None) -> str:
    return "(unknown)" if value is None else value


def _yes_no(value: bool) -> str:
    return "yes" if value else "no"
