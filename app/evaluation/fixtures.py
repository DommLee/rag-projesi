from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from app.schemas import DocumentChunk, SourceType


def _scenario_texts(expected_consistency: str, ticker: str) -> dict[str, str]:
    if expected_consistency == "contradiction":
        return {
            "kap": (
                f"{ticker} resmi KAP bildirimi: güçlü artış, iyileşme ve onay vurgusu; "
                "operasyonel hedeflerde olumlu çerçeve."
            ),
            "news": (
                f"{ticker} medya yorumu: azalış, zayıf görünüm, iptal ve ceza vurgusu; "
                "kısa vadede temkinli çerçeve."
            ),
            "brokerage": f"{ticker} aracı kurum raporu: riskler artıyor, senaryo ayrışıyor.",
        }
    if expected_consistency == "aligned":
        return {
            "kap": (
                f"{ticker} resmi KAP bildirimi: güçlü artış, iyileşme ve onay; "
                "faaliyetlerde dengeli pozitif görünüm."
            ),
            "news": (
                f"{ticker} medya özeti: güçlü artış, iyileşme, onay ifadesi; "
                "resmi açıklama ile uyumlu çerçeve."
            ),
            "brokerage": f"{ticker} aracı kurum raporu: resmi duyurularla uyumlu ana tema.",
        }
    return {
        "kap": (
            f"{ticker} KAP özeti: güçlü artış ile birlikte bazı alanlarda azalış sinyali; "
            "görünüm karma."
        ),
        "news": (
            f"{ticker} haber özeti: kısmi artış ve kısmi zayıf görünüm; "
            "resmi metinle kısmen örtüşen karışık ton."
        ),
        "brokerage": f"{ticker} aracı kurum raporu: senaryo dağılımı dengeli, kesin yön sınırlı.",
    }


def build_eval_fixture_chunks(questions: list[dict[str, Any]]) -> list[DocumentChunk]:
    now = datetime.now(UTC)
    chunks: list[DocumentChunk] = []
    tickers = sorted({item["ticker"].upper() for item in questions})
    expectation_by_ticker = {item["ticker"].upper(): item.get("expected_consistency", "inconclusive") for item in questions}

    for ticker in tickers:
        expected = expectation_by_ticker.get(ticker, "inconclusive")
        texts = _scenario_texts(expected, ticker)
        for idx in range(2):
            day_offset = idx + 1
            kap_dt = now - timedelta(days=day_offset * 5)
            chunks.append(
                DocumentChunk(
                    content=f"{texts['kap']} (fixture_{idx + 1})",
                    ticker=ticker,
                    source_type=SourceType.KAP,
                    publication_date=kap_dt,
                    date=kap_dt,
                    institution="KAP-FIXTURE",
                    notification_type="Material Event",
                    doc_id=f"{ticker}-kap-{idx + 1}",
                    url=f"https://fixture.local/{ticker}/kap/{idx + 1}",
                    published_at=kap_dt,
                    retrieved_at=now,
                    language="tr",
                    confidence=0.98,
                    title=f"{ticker} KAP Fixture {idx + 1}",
                    chunk_id=f"{ticker}-kap-fixture-{idx + 1}",
                    metadata={"fixture": True},
                )
            )

        for idx in range(2):
            day_offset = idx + 1
            news_dt = now - timedelta(days=day_offset * 4)
            chunks.append(
                DocumentChunk(
                    content=f"{texts['news']} (fixture_{idx + 1})",
                    ticker=ticker,
                    source_type=SourceType.NEWS,
                    publication_date=news_dt,
                    date=news_dt,
                    institution="NEWS-FIXTURE",
                    notification_type="General Assembly",
                    doc_id=f"{ticker}-news-{idx + 1}",
                    url=f"https://fixture.local/{ticker}/news/{idx + 1}",
                    published_at=news_dt,
                    retrieved_at=now,
                    language="tr",
                    confidence=0.92,
                    title=f"{ticker} News Fixture {idx + 1}",
                    chunk_id=f"{ticker}-news-fixture-{idx + 1}",
                    metadata={"fixture": True},
                )
            )

        broker_dt = now - timedelta(days=3)
        chunks.append(
            DocumentChunk(
                content=texts["brokerage"],
                ticker=ticker,
                source_type=SourceType.BROKERAGE,
                publication_date=broker_dt,
                date=broker_dt,
                institution="BROKER-FIXTURE",
                notification_type="Financial Report",
                doc_id=f"{ticker}-brokerage-1",
                url=f"https://fixture.local/{ticker}/brokerage/1",
                published_at=broker_dt,
                retrieved_at=now,
                language="tr",
                confidence=0.9,
                title=f"{ticker} Brokerage Fixture 1",
                chunk_id=f"{ticker}-brokerage-fixture-1",
                metadata={"fixture": True},
            )
        )
    return chunks
