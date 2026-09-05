import json
import os
import subprocess
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from ocost.window import Window


@pytest.mark.parametrize("days", [1, 7, 30])
def test_positive_days_are_rolling_periods(days):
    # GIVEN an instant well after the epoch
    now = 1788615906.578
    # WHEN selecting a rolling window
    window = Window.for_days(days, now=now)
    # THEN its duration is exactly N 24-hour periods, independent of local DST
    assert window.end_ms == int(now * 1000)
    assert window.end_ms - window.start_ms == days * 86400000


@pytest.mark.parametrize("days", [None, 999999])
def test_all_time_and_large_windows_start_at_epoch(days):
    # GIVEN all time or a window larger than recorded history
    # WHEN constructing bounds
    window = Window.for_days(days, now=1788615906.578)
    # THEN no history is lost to a recent cutoff or a negative timestamp
    assert window.start_ms == 0
    assert window.end_ms == 1788615906578


@pytest.mark.parametrize(
    "timezone,date",
    [
        ("UTC", "2026-09-05T15:00:00"),
        ("Asia/Kolkata", "2026-09-05T15:00:00"),
        ("America/Los_Angeles", "2026-03-08T15:00:00"),
        ("America/Los_Angeles", "2026-11-01T15:00:00"),
    ],
)
def test_today_starts_at_midnight_including_dst_transition(timezone, date):
    # GIVEN a local timezone, including days whose offset changes after midnight
    zone = ZoneInfo(timezone)
    instant = datetime.fromisoformat(date).replace(tzinfo=zone)
    # WHEN selecting today in a fresh process with that local timezone
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import json,sys; from ocost.window import Window; "
            "print(json.dumps(Window.for_days(0, now=float(sys.argv[1])).params()))",
            str(instant.timestamp()),
        ],
        env={**os.environ, "TZ": timezone},
        text=True,
        capture_output=True,
        check=True,
    )
    # THEN the start is midnight with midnight's offset, not the current one
    params = json.loads(result.stdout)
    expected = instant.replace(hour=0, minute=0, second=0, microsecond=0)
    assert int(params["from"]) == int(expected.timestamp() * 1000)
    assert int(params["to"]) == int(instant.timestamp() * 1000)
