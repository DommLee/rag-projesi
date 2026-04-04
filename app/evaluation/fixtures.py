from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from app.schemas import DocumentChunk, SourceType


def _scenario_texts(expected_consistency: str, ticker: str) -> dict[str, str]:
    if expected_consistency == "contradiction":
        return {
            "kap": (
                f"{ticker} resmi kap bildirimi: guclu artis iyilesme onay vurgusu, "
                "operasyonel hedeflerde olumlu çerçeve."
            ),
            "news": (
                f"{ticker} medya yorumu: azalis zayif iptal ceza reddedildi vurgusu, "
                "kısa vadede temkinli çerçeve."
            ),
            "broker": f"{ticker} aracı kurum raporu: riskler artıyor, senaryo ayrışıyor.",
        }
    if expected_consistency == "aligned":
        return {
            "kap": (
                f"{ticker} resmi kap bildirimi: guclu artis iyilesme onay, "
                "faaliyetlerde dengeli pozitif görünüm."
            ),
            "news": (
                f"{ticker} medya özeti: guclu artis iyilesme onay ifadesi, "
                "resmi açıklama ile uyumlu çerçeve."
            ),
            "broker": f"{ticker} aracı kurum raporu: resmi duyurularla uyumlu ana tema.",
        }
    return {
        "kap": (
            f"{ticker} kap özeti: guclu artis ile birlikte bazı alanlarda azalis sinyali, "
            "görünüm karma."
        ),
        "news": (
            f"{ticker} haber özeti: kısmi artis ve kısmi zayif görünüm, "
            "resmi metinle kısmen örtüşen karışık ton."
        ),
        "broker": f"{ticker} aracı kurum raporu: senaryo dağılımı dengeli, kesin yön sınırlı.",
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
                    date=kap_dt,
                    institution="KAP-FIXTURE",
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
                    date=news_dt,
                    institution="NEWS-FIXTURE",
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
                content=texts["broker"],
                ticker=ticker,
                source_type=SourceType.BROKER_REPORT,
                date=broker_dt,
                institution="BROKER-FIXTURE",
                doc_id=f"{ticker}-broker-1",
                url=f"https://fixture.local/{ticker}/broker/1",
                published_at=broker_dt,
                retrieved_at=now,
                language="tr",
                confidence=0.9,
                title=f"{ticker} Broker Fixture 1",
                chunk_id=f"{ticker}-broker-fixture-1",
                metadata={"fixture": True},
            )
        )
    return chunks

