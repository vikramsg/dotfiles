from pathlib import Path

from ocint.daemon.config import DaemonConfig
from ocint.daemon.lch.systemd import LifecycleStatus
from ocint.daemon.pull_request_job import PullRequestJob, PullRequestJobState
from ocint.presentation import Presentation, Text, data_table, document, key_value_section


def render_status(status: LifecycleStatus, config: DaemonConfig) -> Presentation:
    healthy = status.installed and status.timer_state == "active" and status.last_result in {"success", "unknown"}
    return document(
        "Daemon lifecycle status",
        key_value_section(
            "Summary",
            [
                ("Installed", _styled("yes" if status.installed else "no", "green" if status.installed else "red")),
                ("Health", _styled("ready" if healthy else "attention required", "green" if healthy else "red")),
            ],
        ),
        key_value_section(
            "Timer",
            [
                ("State", _state(status.timer_state, status.timer_substate)),
                ("Last trigger", status.last_trigger),
                ("Next trigger", status.next_trigger),
            ],
        ),
        key_value_section(
            "Service",
            [
                ("State", _state(status.service_state, status.service_substate)),
                ("Result", _result(status.last_result)),
                ("Exit status", status.last_exit_status),
                ("Started", status.last_started),
                ("Completed", status.last_completed),
            ],
        ),
        key_value_section(
            "Lifecycle",
            [
                ("Startup delay", _duration(config.lifecycle.startup_delay_seconds)),
                ("Inactive interval", _duration(config.lifecycle.inactive_interval_seconds)),
                ("Idle shutdown", _duration(config.idle_timeout_seconds)),
            ],
        ),
        key_value_section(
            "Logging",
            [
                ("Rotation", _bytes(config.logging.max_bytes)),
                ("Backups retained", config.logging.backup_count),
            ],
        ),
        key_value_section("Files", [("Log", _home_relative(status.log_path, status.home))]),
        key_value_section(
            "Actions",
            [
                ("View logs", Text("ocint daemon lch logs --lines 100", style="bold magenta")),
                ("Follow logs", Text("ocint daemon lch logs --follow", style="bold magenta")),
            ],
        ),
    )


def render_jobs(jobs: list[PullRequestJob]) -> Presentation:
    return document(
        "Daemon jobs",
        data_table(
            "Recent jobs",
            ("ID", "State", "Stage", "Title"),
            (
                (
                    job.id,
                    job.state.value,
                    job.stage.value,
                    job.title,
                )
                for job in jobs
            ),
            empty_message="No daemon jobs have been recorded.",
        ),
    )


def render_job(job: PullRequestJob) -> Presentation:
    sections: list[Presentation] = [
        key_value_section(
            "Job",
            [
                ("ID", job.id),
                ("State", _job_state(job.state)),
                ("Stage", job.stage.value),
                ("Repository", job.repository),
                ("Title", job.title),
                ("Actor", str(job.actor)),
                ("Created", job.created_at),
                ("Updated", job.updated_at),
            ],
        ),
        key_value_section(
            "Execution",
            [
                ("Session", job.session_id or "unavailable"),
                ("Worktree", str(job.worktree_path or "unavailable")),
                ("Branch", job.branch or "unavailable"),
                ("Commit", job.commit_sha or "unavailable"),
            ],
        ),
        key_value_section(
            "Result",
            [
                ("Pull request", job.pull_request_url or "unavailable"),
                ("Error", job.error or "none"),
            ],
        ),
    ]
    if job.state is PullRequestJobState.RUNNING and job.session_id:
        sections.append(
            key_value_section(
                "Actions",
                [("Attach", Text(f"ocint daemon lch attach {job.id}", style="bold magenta"))],
            )
        )
    return document("Daemon job status", *sections)


def _job_state(state: PullRequestJobState) -> Text:
    style = {
        PullRequestJobState.QUEUED: "yellow",
        PullRequestJobState.RUNNING: "cyan",
        PullRequestJobState.COMPLETED: "green",
        PullRequestJobState.FAILED: "red",
    }[state]
    return _styled(state.value, style)


def _state(state: str, substate: str) -> Text:
    style = "green" if state == "active" else ("red" if state == "failed" else "yellow")
    return _styled(f"{state} / {substate}", style)


def _result(result: str) -> Text:
    style = "green" if result == "success" else ("yellow" if result == "unknown" else "red")
    return _styled(result, style)


def _styled(value: str, style: str) -> Text:
    return Text(value, style=style)


def _home_relative(path: Path, home: Path) -> str:
    try:
        return f"~/{path.resolve().relative_to(home.resolve()).as_posix()}"
    except ValueError:
        return str(path)


def _duration(seconds: int) -> str:
    return f"{seconds // 60}m" if seconds % 60 == 0 else f"{seconds}s"


def _bytes(value: int) -> str:
    return f"{value // (1024 * 1024)} MiB" if value % (1024 * 1024) == 0 else f"{value} bytes"
