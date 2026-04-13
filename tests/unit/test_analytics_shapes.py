from datetime import UTC, datetime, timedelta

from app.schemas import DocumentChunk, SourceType
from app.utils.analytics import broker_bias_lens, tension_timeline


def _chunk(content: str, source_type: SourceType, institution: str, days_ago: int) -> DocumentChunk:
    dt = datetime.now(UTC) - timedelta(days=days_ago)
    return DocumentChunk(
        content=content,
        ticker="ASELS",
        source_type=source_type,
        institution=institution,
        notification_type="Material Event",
        doc_id=f"{institution}-{days_ago}",
        url=f"https://example.com/{institution}/{days_ago}",
        title=f"{institution} item",
        date=dt,
        published_at=dt,
    )


def test_tension_timeline_returns_weekly_rows() -> None:
    rows = [
        _chunk("aselsan güçlü büyüme onay aldı", SourceType.KAP, "KAP", 14),
        _chunk("aselsan güçlü büyüme haberi", SourceType.NEWS, "AA", 14),
        _chunk("aselsan ceza ve gerileme riski", SourceType.KAP, "KAP", 2),
        _chunk("aselsan büyüme beklentisi zayıf", SourceType.NEWS, "Bloomberg HT", 2),
    ]
    result = tension_timeline(rows)
    assert "weekly_tension" in result
    assert isinstance(result["weekly_tension"], list)
    assert result["weekly_tension"]
    assert "week" in result["weekly_tension"][0]


def test_broker_bias_lens_returns_institution_summary() -> None:
    rows = [
        _chunk("savunma ihracat büyüme marj", SourceType.BROKERAGE, "İş Yatırım", 7),
        _chunk("savunma ihracat sipariş büyüme", SourceType.BROKERAGE, "İş Yatırım", 6),
        _chunk("nakit akışı değerleme risk", SourceType.BROKERAGE, "Ak Yatırım", 5),
    ]
    result = broker_bias_lens(rows)
    assert "institutions" in result
    assert isinstance(result["institutions"], list)
    assert result["institutions"][0]["institution"]
    assert "theme_score" in result["institutions"][0]
