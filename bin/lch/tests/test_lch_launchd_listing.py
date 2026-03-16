import plistlib
from pathlib import Path
from types import SimpleNamespace

from click.testing import CliRunner


def write_plist(path: Path, payload: dict[str, object]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(plistlib.dumps(payload))
    return path


def test_discover_launchd_jobs_reads_labels_and_skips_invalid_plists(tmp_path, monkeypatch):
    from lch import launchd as launchd_module

    agent_dir = tmp_path / "Library/LaunchAgents"
    daemon_dir = tmp_path / "Library/LaunchDaemons"
    write_plist(agent_dir / "good.agent.plist", {"Label": "com.example.agent"})
    write_plist(daemon_dir / "good.daemon.plist", {"Label": "com.example.daemon"})
    write_plist(agent_dir / "missing-label.plist", {"ProgramArguments": ["true"]})
    (agent_dir / "broken.plist").write_text("not a plist")

    monkeypatch.setattr(launchd_module, "is_job_loaded", lambda label: label == "com.example.agent")

    jobs = launchd_module.discover_launchd_jobs(search_roots=[agent_dir, daemon_dir])

    assert [job.label for job in jobs] == ["com.example.agent", "com.example.daemon"]
    assert jobs[0].kind == "agent"
    assert jobs[0].loaded is True
    assert jobs[1].kind == "daemon"
    assert jobs[1].loaded is False


def test_paginate_launchd_jobs_slices_results_and_tracks_metadata():
    from lch.launchd import paginate_launchd_jobs

    jobs = [SimpleNamespace(label=f"job-{idx}", kind="agent", loaded=False, source="~/Library/LaunchAgents") for idx in range(5)]

    page = paginate_launchd_jobs(jobs, page=2, page_size=2)

    assert page.page == 2
    assert page.page_size == 2
    assert page.total_items == 5
    assert page.total_pages == 3
    assert [job.label for job in page.items] == ["job-2", "job-3"]


def test_launchd_page_renders_requested_page(monkeypatch):
    import lch.cli as cli_module

    jobs = [
        SimpleNamespace(label="com.example.agent1", kind="agent", loaded=True, source="~/Library/LaunchAgents"),
        SimpleNamespace(label="com.example.agent2", kind="agent", loaded=False, source="~/Library/LaunchAgents"),
        SimpleNamespace(label="com.example.agent3", kind="agent", loaded=True, source="~/Library/LaunchAgents"),
    ]
    monkeypatch.setattr(cli_module, "discover_launchd_jobs", lambda: jobs)

    runner = CliRunner()
    result = runner.invoke(cli_module.main, ["launchd", "page", "--page", "2", "--page-size", "2"])

    assert result.exit_code == 0
    assert "PAGE 2/2" in result.output
    assert "com.example.agent3" in result.output
    assert "com.example.agent1" not in result.output


def test_launchd_list_uses_pager_when_stdout_is_a_tty(monkeypatch):
    import lch.cli as cli_module

    monkeypatch.setattr(cli_module, "stdout_supports_pager", lambda: True)
    monkeypatch.setattr(cli_module, "render_full_launchd_job_list", lambda: "FULL\ncom.example.agent1\ncom.example.agent2")

    pager_output: list[str] = []
    normal_output: list[str] = []
    monkeypatch.setattr(cli_module.click, "echo_via_pager", pager_output.append)
    monkeypatch.setattr(cli_module.click, "echo", normal_output.append)

    runner = CliRunner()
    result = runner.invoke(cli_module.main, ["launchd", "list"])

    assert result.exit_code == 0
    assert pager_output == ["FULL\ncom.example.agent1\ncom.example.agent2"]
    assert normal_output == []


def test_launchd_list_prints_normally_when_stdout_is_not_a_tty(monkeypatch):
    import lch.cli as cli_module

    monkeypatch.setattr(cli_module, "stdout_supports_pager", lambda: False)
    monkeypatch.setattr(cli_module, "render_full_launchd_job_list", lambda: "FULL\ncom.example.agent1\ncom.example.agent2")

    pager_output: list[str] = []
    normal_output: list[str] = []
    monkeypatch.setattr(cli_module.click, "echo_via_pager", pager_output.append)
    monkeypatch.setattr(cli_module.click, "echo", normal_output.append)

    runner = CliRunner()
    result = runner.invoke(cli_module.main, ["launchd", "list"])

    assert result.exit_code == 0
    assert pager_output == []
    assert normal_output == ["FULL\ncom.example.agent1\ncom.example.agent2"]
