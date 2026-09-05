"""Translate day selection into one fixed API time range."""

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class Window:
    start_ms: int
    end_ms: int
    label: str

    @classmethod
    def for_days(cls, days: int | None, *, now: float) -> Window:
        end = int(now * 1000)
        if days is None:
            return cls(0, end, "All time")
        if not 0 <= days <= 999999:
            raise ValueError("days must be between 0 and 999999")
        if days == 0:
            # Keep this naive until timestamp(): the OS resolves midnight's DST
            # offset, which can differ from the current offset on transition days.
            midnight = datetime.fromtimestamp(now).replace(hour=0, minute=0, second=0, microsecond=0)
            return cls(int(midnight.timestamp() * 1000), end, "Today · local midnight onward")
        return cls(max(0, end - days * 86400000), end, f"Last {days} days · rolling 24 hours")

    def params(self) -> dict[str, str]:
        return {"from": str(self.start_ms), "to": str(self.end_ms)}
