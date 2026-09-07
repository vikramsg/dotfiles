"""Project selection and accounting for completed usage reports."""

from collections.abc import Iterable
from datetime import date, timedelta
from pathlib import PurePosixPath

from ocost.models import Activity, ModelUsage, Project, Report, Stats, Tokens


class ProjectSelectionError(Exception):
    """A project selector did not identify exactly one discovered project."""


def resolve_projects(projects: Iterable[Project], selectors: Iterable[str]) -> set[str]:
    """Resolve IDs, canonical paths, and unambiguous canonical basenames."""
    available = list(projects)
    excluded: set[str] = set()
    for selector in selectors:
        by_id = [project for project in available if project.id == selector]
        by_path = [project for project in available if project.canonical == selector]
        by_name = [project for project in available if PurePosixPath(project.canonical).name == selector]
        matches = by_id or by_path or by_name
        if not matches:
            raise ProjectSelectionError(f"Unknown project selector: {selector!r}")
        if len(matches) > 1:
            raise ProjectSelectionError(f"Ambiguous project selector: {selector!r}")
        excluded.add(matches[0].id)
    return excluded


def exclude_projects(report: Report, project_ids: set[str]) -> Report:
    """Remove selected project usage from project rows and overall totals."""
    excluded = [row for row in report.projects if row.project.id in project_ids]
    overall = report.overall.model_copy(deep=True)
    for row in excluded:
        _subtract_stats(overall.data, row.usage.data)
    return Report(overall, [row for row in report.projects if row.project.id not in project_ids])


def _subtract_stats(overall: Stats, excluded: Stats) -> None:
    overall.cost -= excluded.cost
    overall.sessions -= excluded.sessions
    overall.subagents -= excluded.subagents
    overall.prompts -= excluded.prompts
    overall.steps -= excluded.steps
    _subtract_tokens(overall.tokens, excluded.tokens)
    _subtract_models(overall.models, excluded.models)
    _subtract_activity(overall, excluded)
    _subtract_tools(overall, excluded)


def _subtract_tokens(overall: Tokens, excluded: Tokens) -> None:
    overall.input -= excluded.input
    overall.output -= excluded.output
    overall.reasoning -= excluded.reasoning
    overall.cache.read -= excluded.cache.read
    overall.cache.write -= excluded.cache.write


def _subtract_models(overall: list[ModelUsage], excluded: list[ModelUsage]) -> None:
    by_model: dict[tuple[str, str, str | None], ModelUsage] = {}
    for usage in overall:
        key = _model_key(usage)
        if aggregate := by_model.get(key):
            aggregate.cost += usage.cost
            aggregate.steps += usage.steps
            _add_tokens(aggregate.tokens, usage.tokens)
        else:
            by_model[key] = usage
    for usage in excluded:
        if aggregate := by_model.get(_model_key(usage)):
            aggregate.cost -= usage.cost
            aggregate.steps -= usage.steps
            _subtract_tokens(aggregate.tokens, usage.tokens)
    overall[:] = [usage for usage in by_model.values() if _has_model_usage(usage)]


def _add_tokens(total: Tokens, addition: Tokens) -> None:
    total.input += addition.input
    total.output += addition.output
    total.reasoning += addition.reasoning
    total.cache.read += addition.cache.read
    total.cache.write += addition.cache.write


def _subtract_activity(overall: Stats, excluded: Stats) -> None:
    if overall.activity is None or excluded.activity is None:
        return
    by_date: dict[date, Activity] = {}
    for activity in overall.activity:
        if aggregate := by_date.get(activity.date):
            aggregate.steps += activity.steps
        else:
            by_date[activity.date] = activity
    for activity in excluded.activity:
        if aggregate := by_date.get(activity.date):
            aggregate.steps -= activity.steps
    overall.activity = sorted(
        (activity for activity in by_date.values() if activity.steps), key=lambda activity: activity.date
    )
    if overall.activeDays is not None:
        overall.activeDays = len(overall.activity)
    if overall.streak is not None:
        overall.streak = _longest_streak(overall.activity)


def _longest_streak(activity: list[Activity]) -> int:
    longest = current = 0
    previous: date | None = None
    for row in activity:
        current = current + 1 if previous is not None and row.date == previous + timedelta(days=1) else 1
        longest = max(longest, current)
        previous = row.date
    return longest


def _subtract_tools(overall: Stats, excluded: Stats) -> None:
    if overall.tools is None or excluded.tools is None:
        return
    total = overall.tools.totals
    removed = excluded.tools.totals
    total.calls -= removed.calls
    total.succeeded -= removed.succeeded
    total.failed -= removed.failed
    total.unfinished -= removed.unfinished


def _model_key(usage: ModelUsage) -> tuple[str, str, str | None]:
    return (usage.model.providerID, usage.model.id, usage.model.variant)


def _has_model_usage(usage: ModelUsage) -> bool:
    return bool(usage.cost or usage.steps or any(usage.tokens.values()))
