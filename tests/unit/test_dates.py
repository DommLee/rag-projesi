from datetime import UTC

from app.utils.dates import parse_date


def test_parse_date_from_string() -> None:
    parsed = parse_date("2026-01-01T10:00:00+03:00")
    assert parsed.tzinfo is not None
    assert parsed.astimezone(UTC).hour == 7


def test_parse_date_none_returns_now() -> None:
    parsed = parse_date(None)
    assert parsed.tzinfo is not None

