import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta


@dataclass(frozen=True)
class UsageWindow:
    since: date | None = None
    until: date | None = None
    start_ms: int | None = None
    end_ms: int | None = None

    @property
    def label(self) -> str:
        if self.since is None and self.until is None:
            return "all"
        start = self.since.isoformat() if self.since else "beginning"
        end = self.until.isoformat() if self.until else "now"
        return f"{start}..{end}"


def parse_yyyy_mm_dd(value: str | None) -> date | None:
    if value is None:
        return None
    return date.fromisoformat(value)


def make_window(*, since: str | None = None, until: str | None = None, days: int | None = None) -> UsageWindow:
    since_date = parse_yyyy_mm_dd(since)
    until_date = parse_yyyy_mm_dd(until)
    if days is not None:
        if days <= 0:
            raise ValueError("--days must be greater than zero")
        if since_date is None:
            anchor_date = until_date or datetime.now(UTC).date()
            since_date = anchor_date - timedelta(days=days - 1)

    if since_date is not None and until_date is not None and since_date > until_date:
        raise ValueError("--since must be on or before --until")

    start_ms = _start_of_day_ms(since_date) if since_date else None
    end_ms = _start_of_day_ms(until_date + timedelta(days=1)) if until_date else None
    return UsageWindow(since=since_date, until=until_date, start_ms=start_ms, end_ms=end_ms)


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
