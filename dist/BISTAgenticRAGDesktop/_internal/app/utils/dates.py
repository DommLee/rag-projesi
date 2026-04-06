from __future__ import annotations

from datetime import UTC, datetime

from dateutil import parser


def parse_date(value: str | datetime | None) -> datetime:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)
    if not value:
        return datetime.now(UTC)
    parsed = parser.parse(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def now_utc() -> datetime:
    return datetime.now(UTC)

