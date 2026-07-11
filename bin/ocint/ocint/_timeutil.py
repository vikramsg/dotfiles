import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta


@dataclass(frozen=True)
class UsageWindow:
    start_ms: int | None = None
    description: str = "all"

    @property
    def label(self) -> str:
        return self.description


def make_window(*, days: int | None = None, now: datetime | None = None) -> UsageWindow:
    if days is None:
        return UsageWindow()
    if days < 0:
        raise ValueError("--days must be zero or greater")
    if now is not None and now.tzinfo is None:
        raise ValueError("now must include a timezone")
    current = now or datetime.now()
    if days == 0:
        start_ms = int(current.replace(hour=0, minute=0, second=0, microsecond=0).timestamp() * 1000)
        description = "today"
    else:
        start_ms = int(current.timestamp() * 1000) - days * 86_400_000
        description = f"last {days} days"
    return UsageWindow(start_ms=start_ms, description=description)


def parse_since_ms(value: str | None) -> int | None:
    if value is None:
        return None
    stripped = value.strip().lower()
    if not stripped:
        raise ValueError("--since requires a value")
    if match := re.fullmatch(r"(\d+)([dhw])", stripped):
        amount = int(match.group(1))
        if amount <= 0:
            raise ValueError("--since duration must be greater than zero")
        unit = match.group(2)
        delta = {"d": timedelta(days=amount), "h": timedelta(hours=amount), "w": timedelta(weeks=amount)}[unit]
        return int((datetime.now(UTC) - delta).timestamp() * 1000)
    parsed_date = date.fromisoformat(stripped)
    return _start_of_day_ms(parsed_date)


def format_ms(value: int | None) -> str:
    if value is None:
        return ""
    return datetime.fromtimestamp(value / 1000, tz=UTC).isoformat().replace("+00:00", "Z")


def _start_of_day_ms(value: date) -> int:
    return int(datetime.combine(value, datetime.min.time(), tzinfo=UTC).timestamp() * 1000)
