import copy
from io import StringIO

from rich.console import Console

from ocost.models import Project, ProjectUsage, Report, StatsResponse
from ocost.render import render_report
from ocost.window import Window


def test_render_contains_sorted_costs_and_literal_model_identities(report):
    # GIVEN two models whose ID is shared but provider/variant differ
    report.projects[0].usage.data.models[0].model.id = "[red]literal[/red]"
    output = StringIO()
    # WHEN rendering the report (content checks only, not a visual snapshot)
    Console(file=output, width=160).print(render_report(report, Window(0, 1000, "All time"), width=160))
    text = output.getvalue()
    # THEN cost order and literal identities are retained with readable values
    assert text.index("other / same-model (default)") < text.index("azure / [red]literal[/red] (medium)")
    for value in ["$12.125000", "$10.000000", "$2.125000", "1,200", "8,000", "500", "90"]:
        assert value in text
    assert "Roots" in text and "Subs" in text and "Prompts" in text


def test_projects_sorted_and_same_directory_records_not_merged(report, stats_payload):
    # GIVEN two IDs sharing the same directory and prefix
    report.projects[0].project.id = "sameprefix-one"
    payload = copy.deepcopy(stats_payload)
    payload["data"]["cost"] = 99
    report.projects.append(
        ProjectUsage(Project(id="sameprefix-two", canonical="/work/dotfiles"), StatsResponse.model_validate(payload))
    )
    output = StringIO()
    # WHEN reporting both
    Console(file=output, width=160).print(render_report(report, Window(0, 1000, "All time"), width=160))
    text = output.getvalue()
    # THEN both are identifiable and the higher-cost project appears first
    assert text.index("[sameprefix-two]") < text.index("[sameprefix-one]")
    assert "project costs do not reconcile" in text
    assert len(report.json_data()["projects"]) == 2


def test_zero_cost_usage_stays_visible(report):
    # GIVEN recorded tokens/steps without a configured cost
    report.projects[0].usage.data.cost = 0
    for model in report.projects[0].usage.data.models:
        model.cost = 0
    output = StringIO()
    # WHEN displaying usage
    Console(file=output, width=160).print(render_report(report, Window(0, 1000, "All time"), width=160))
    # THEN it remains visible despite having no cost
    assert "same-model" in output.getvalue()
    assert "$0.000000" in output.getvalue()
    assert "8,000" in output.getvalue()


def test_empty_window_has_explicit_empty_state(stats_payload):
    # GIVEN no usage in the selected window
    data = stats_payload["data"]
    for field in ["cost", "sessions", "subagents", "prompts", "steps"]:
        data[field] = 0
    data["tokens"] = {"input": 0, "output": 0, "reasoning": 0, "cache": {"read": 0, "write": 0}}
    data["models"] = []
    report = Report(StatsResponse.model_validate(stats_payload), [])
    output = StringIO()
    # WHEN rendering the report
    Console(file=output).print(render_report(report, Window(0, 1000, "Today"), width=80))
    # THEN empty usage is clear, not confused with an error
    assert "No project usage in this window." in output.getvalue()
    assert "$0.000000" in output.getvalue()


def test_json_keeps_optional_absence_and_unknown_fields(report, stats_payload):
    # GIVEN API fields unused by the renderer and an omitted variant
    # WHEN serializing for machines
    data = report.json_data()
    # THEN no defaults are injected and no unknown fields disappear
    assert {key: value for key, value in data.items() if key != "projects"} == stats_payload
    assert data["projects"][0]["usage"] == stats_payload
