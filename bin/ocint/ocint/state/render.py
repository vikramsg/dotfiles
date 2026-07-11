from collections.abc import Mapping, Sequence

from ocint._models import ResolvedPaths
from ocint._timeutil import UsageWindow
from ocint.presentation import Presentation, data_table, document, key_value_section
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
                ("Message-attributed cost", _format_cost(detailed.message_attributed_cost)),
            ],
        ),
        data_table(
            "By project",
            ("Project", "Cost"),
            ((_source_label(row.worktree), _format_cost(row.cost)) for row in detailed.projects),
        ),
        data_table(
            "By agent",
            ("Agent", "Cost"),
            ((f"{row.agent} ({row.kind})", _format_cost(row.cost)) for row in detailed.agents),
        ),
        data_table(
            "By project / agent",
            ("Project / agent", "Cost"),
            (
                (f"{_source_label(row.worktree)}: {row.agent} ({row.kind})", _format_cost(row.cost))
                for row in detailed.project_agents
            ),
        ),
    )


def render_sessions(sessions: Sequence[StateSessionUsage], window: UsageWindow) -> Presentation:
    return document(
        "OpenCode session usage",
        key_value_section("Selection", [("Window", window.label), ("Sessions", _format_int(len(sessions)))]),
        data_table(
            "Sessions",
            ("Session", "First seen", "Last seen", "Messages", "Cost", "Tokens"),
            (
                (
                    session.session_id,
                    session.first_seen.isoformat(),
                    session.last_seen.isoformat(),
                    _format_int(session.messages),
                    _format_cost(session.cost),
                    _format_tokens(session.tokens),
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


def _format_tokens(tokens: UsageTokens) -> str:
    return "\n".join(f"{label}: {value}" for label, value in _token_rows(tokens))


def _format_int(value: int) -> str:
    return f"{value:,}"


def _format_cost(value: float) -> str:
    return f"{value:.6f}"


def _source_label(value: str | None) -> str:
    return "(unknown)" if value is None else value


def _yes_no(value: bool) -> str:
    return "yes" if value else "no"
