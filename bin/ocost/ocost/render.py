"""Independent Rich presentation, visually consistent with the existing tools."""

from collections import Counter
from pathlib import PurePosixPath

from rich.console import Group
from rich.rule import Rule
from rich.table import Table
from rich.text import Text

from ocost.models import ModelUsage, ProjectUsage, Report, Tokens
from ocost.window import Window


def number(value: int | float) -> str:
    return f"{value:,}" if isinstance(value, int) else f"{value:,.6f}".rstrip("0").rstrip(".")


def money(value: int | float) -> str:
    return f"${value:,.6f}"


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
            result.add_row(Text(label), *(number(value) for value in tokens.values()))
    else:
        result = table("Usage", "Tokens", "Cache")
        for label, tokens in rows:
            result.add_row(
                Text(label),
                "\n".join(
                    f"{label}: {number(value)}"
                    for label, value in zip(
                        ["Input", "Output", "Reasoning"],
                        tokens.values()[:3],
                        strict=True,
                    )
                ),
                "\n".join(
                    f"{label}: {number(value)}"
                    for label, value in zip(
                        ["Read", "Write"],
                        tokens.values()[3:],
                        strict=True,
                    )
                ),
                end_section=True,
            )
    return result


def render_report(report: Report, window: Window, *, width: int) -> Group:
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
    projects = table("Project", "Cost (USD)", "Roots", "Subs", "Prompts", "Steps")
    for row in rows:
        stats = row.usage.data
        projects.add_row(
            Text(labels[row.project.id]),
            money(stats.cost),
            number(stats.sessions),
            number(stats.subagents),
            number(stats.prompts),
            number(stats.steps),
        )

    content: list[Group | Text] = [
        Text("OpenCode usage", style="bold green"),
        Text(""),
        section("Summary", summary),
        section("By project", projects if rows else Text("No project usage in this window.", style="dim")),
        section("Total tokens", token_table([("All projects", overall.tokens)], width=width)),
    ]
    for row in rows:
        stats = row.usage.data
        models = sorted(stats.models, key=lambda item: (-item.cost, model_label(item)))
        costs = table("Provider / model (variant)", "Cost (USD)", "Steps")
        for model in models:
            costs.add_row(Text(model_label(model)), money(model.cost), number(model.steps))
        content.append(section(labels[row.project.id], costs if models else Text("No model usage.", style="dim")))
        content.append(
            section(
                "Tokens",
                token_table(
                    [(model_label(model), model.tokens) for model in models] + [("Project total", stats.tokens)],
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
    content.append(Text("Source: OpenCode V2 API · costs as reported, not a billing statement", style="dim"))
    return Group(*content)
