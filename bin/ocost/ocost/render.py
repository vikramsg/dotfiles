"""Independent Rich presentation, visually consistent with the existing tools."""

from collections import Counter
from pathlib import PurePosixPath

from rich.console import Group
from rich.rule import Rule
from rich.table import Table
from rich.text import Text

from ocost.models import ModelUsage, ProjectUsage, Report, Tokens
from ocost.window import Window

COMPACT_ROW_LIMIT = 5


def number(value: int | float) -> str:
    return f"{value:,}" if isinstance(value, int) else f"{value:,.6f}".rstrip("0").rstrip(".")


def money(value: int | float) -> str:
    return f"${value:,.6f}"


def token_count(value: int | float) -> str:
    return f"{value / 1_000_000:,.2f}M"


def table(*columns: str) -> Table:
    result = Table(box=None, show_edge=False, pad_edge=False, header_style="bold", padding=(0, 1))
    for index, column in enumerate(columns):
        result.add_column(column, justify="left" if index == 0 else "right", overflow="fold")
    return result


def section(title: str, content: Table | Text) -> Group:
    return Group(Rule(Text(title), style="cyan", align="left"), Text(""), content, Text(""))


def model_label(usage: ModelUsage) -> str:
    model = usage.model
    return f"{model.providerID} / {model.id} ({model.variant if model.variant is not None else 'default'})"


def project_labels(rows: list[ProjectUsage]) -> dict[str, str]:
    names = [PurePosixPath(row.project.canonical).name or "/" for row in rows]
    counts = Counter(names)
    paths = Counter(row.project.canonical for row in rows)
    prefixes = Counter(row.project.id[:8] for row in rows)
    labels = {}
    for row, name in zip(rows, names, strict=True):
        project = row.project
        label = project.canonical if counts[name] > 1 else name
        if paths[project.canonical] > 1:
            suffix = project.id if prefixes[project.id[:8]] > 1 else project.id[:8]
            label += f" [{suffix}]"
        labels[project.id] = label
    return labels


def token_table(rows: list[tuple[str, Tokens]], *, width: int) -> Table:
    if width >= 110:
        result = table("Usage", "Input", "Output", "Reasoning", "Cache read", "Cache write")
        for label, tokens in rows:
            result.add_row(Text(label), *(token_count(value) for value in tokens.values()))
    else:
        result = table("Usage", "Tokens", "Cache")
        for label, tokens in rows:
            result.add_row(
                Text(label),
                "\n".join(
                    f"{label}: {token_count(value)}"
                    for label, value in zip(
                        ["Input", "Output", "Reasoning"],
                        tokens.values()[:3],
                        strict=True,
                    )
                ),
                "\n".join(
                    f"{label}: {token_count(value)}"
                    for label, value in zip(
                        ["Read", "Write"],
                        tokens.values()[3:],
                        strict=True,
                    )
                ),
                end_section=True,
            )
    return result


def project_table(rows: list[ProjectUsage], *, limit: int | None = None) -> Table:
    labels = project_labels(rows)
    visible = rows if limit is None else rows[:limit]
    result = table("Project", "Cost (USD)", "Roots", "Subs", "Prompts", "Steps")
    for row in visible:
        stats = row.usage.data
        result.add_row(
            Text(labels[row.project.id]),
            money(stats.cost),
            number(stats.sessions),
            number(stats.subagents),
            number(stats.prompts),
            number(stats.steps),
        )
    if limit is not None and len(rows) > limit:
        result.add_row(Text(f"… {len(rows) - limit} more — use --verbose"), *([""] * 5))
    return result


def model_table(models: list[ModelUsage], *, limit: int | None = None) -> Table:
    visible = models if limit is None else models[:limit]
    result = table("Provider / model (variant)", "Cost (USD)", "Steps")
    for model in visible:
        result.add_row(Text(model_label(model)), money(model.cost), number(model.steps))
    if limit is not None and len(models) > limit:
        result.add_row(Text(f"… {len(models) - limit} more — use --verbose"), "", "")
    return result


def render_report(report: Report, window: Window, *, width: int, verbose: bool = False) -> Group:
    overall = report.overall.data
    summary = Table.grid(padding=(0, 2))
    summary.add_column(style="bold")
    summary.add_column()
    for label, value in [
        ("Window", window.label),
        ("Total cost", money(overall.cost)),
        ("Sessions", f"{overall.sessions:,} roots · {overall.subagents:,} subagents"),
        ("Activity", f"{overall.prompts:,} prompts · {overall.steps:,} assistant steps"),
    ]:
        summary.add_row(Text(label), Text(value))

    rows = [row for row in report.ordered_projects() if row.usage.data.has_usage()]
    labels = project_labels(rows)
    models = sorted(overall.models, key=lambda item: (-item.cost, model_label(item)))
    row_limit = None if verbose else COMPACT_ROW_LIMIT

    content: list[Group | Text] = [
        Text("OpenCode usage", style="bold green"),
        Text(""),
        section("Summary", summary),
        section(
            "By project",
            project_table(rows, limit=row_limit) if rows else Text("No project usage in this window.", style="dim"),
        ),
        section("By model", model_table(models, limit=row_limit) if models else Text("No model usage.", style="dim")),
    ]
    if verbose:
        content.append(section("Total tokens", token_table([("All projects", overall.tokens)], width=width)))
        for row in rows:
            stats = row.usage.data
            project_models = sorted(stats.models, key=lambda item: (-item.cost, model_label(item)))
            content.append(
                section(
                    labels[row.project.id],
                    model_table(project_models) if project_models else Text("No model usage.", style="dim"),
                )
            )
            content.append(
                section(
                    "Tokens",
                    token_table(
                        [(model_label(model), model.tokens) for model in project_models]
                        + [("Project total", stats.tokens)],
                        width=width,
                    ),
                )
            )

    if abs(report.cost_difference()) > 0.000001:
        content.append(
            Text(
                "Note: project costs do not reconcile to the overall total. "
                "API requests are separate reads, not an atomic snapshot.",
                style="yellow",
            )
        )
    return Group(*content)
