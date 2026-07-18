import re
from io import StringIO
from pathlib import Path

from ocint.daemon.lch.render import render_status
from ocint.daemon.lch.systemd import LifecycleStatus
from rich.console import Console


def test_status_rendering_has_colored_sections_and_copyable_log_commands(tmp_path: Path) -> None:
    # GIVEN
    status = LifecycleStatus(
        installed=True,
        timer_state="active",
        timer_substate="waiting",
        last_trigger="2026-07-18 06:26:10 UTC",
        next_trigger="2026-07-18 06:42:44 UTC",
        service_state="inactive",
        service_substate="dead",
        last_result="success",
        last_exit_status="0",
        last_started="2026-07-18 06:26:10 UTC",
        last_completed="2026-07-18 06:27:44 UTC",
        log_path=tmp_path / "home" / ".local" / "state" / "ocint" / "daemon.log",
        home=tmp_path / "home",
    )
    output = StringIO()
    console = Console(file=output, force_terminal=True, color_system="standard", width=100)

    # WHEN
    console.print(render_status(status))
    rendered = output.getvalue()

    # THEN
    assert "Daemon lifecycle status" in rendered
    assert "Summary" in rendered
    assert "Timer" in rendered
    assert "Service" in rendered
    assert "Files" in rendered
    assert "Actions" in rendered
    assert "ocint daemon lch logs --lines 100" in rendered
    assert "ocint daemon lch logs --follow" in rendered
    assert re.search(r"\x1b\[[0-9;]*32m", rendered)
    assert re.search(r"\x1b\[[0-9;]*36m", rendered)
    assert re.search(r"\x1b\[[0-9;]*35m", rendered)
