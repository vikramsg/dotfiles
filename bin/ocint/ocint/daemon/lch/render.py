from pathlib import Path

from ocint.daemon.config import DaemonConfig
from ocint.daemon.lch.systemd import LifecycleStatus
from ocint.presentation import Presentation, Text, document, key_value_section


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
