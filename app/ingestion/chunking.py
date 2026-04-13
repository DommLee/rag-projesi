from __future__ import annotations

import hashlib
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.nlp.sentiment import score_turkish_financial_sentiment
from app.schemas import DocumentChunk, SourceType
from app.utils.dates import parse_date


@dataclass
class RawDoc:
    ticker: str
    source_type: SourceType
    institution: str
    url: str
    title: str
    text: str
    date: datetime | str | None
    published_at: datetime | str | None
    retrieved_at: datetime | str | None
    notification_type: str = "General Assembly"
    language: str = "tr"
    confidence: float = 0.8
    doc_id: str | None = None
    metadata: dict[str, Any] | None = None


def _chunk_id(seed: str) -> str:
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()[:32]


def split_text(text: str, chunk_size: int = 900, overlap: int = 150) -> Iterable[str]:
    text = " ".join(text.split())
    if not text:
        return []
    chunks = []
    cursor = 0
    while cursor < len(text):
        end = min(len(text), cursor + chunk_size)
        chunks.append(text[cursor:end])
        cursor = max(end - overlap, cursor + 1)
        if end == len(text):
            break
    return chunks


def _build_context_prefix(raw: RawDoc, total_chunks: int) -> str:
    """Build a short context prefix for contextual chunking.

    This prefix is prepended to each chunk so the embedding captures
    the document's provenance — ticker, source type, institution, date,
    and notification type.  Inspired by Anthropic's contextual retrieval
    technique which reduces top-20 retrieval failure by ~49%.
    """
    parts = [f"[{raw.ticker}]"]
    source_label = {
        "kap": "KAP bildirimi",
        "news": "haber",
        "brokerage": "araci kurum raporu",
        "user_upload": "kullanici dosyasi",
    }.get(raw.source_type.value, raw.source_type.value)
    parts.append(source_label)
    if raw.institution:
        parts.append(f"kaynak: {raw.institution}")
    if raw.notification_type and raw.notification_type != "General Assembly":
        parts.append(f"tur: {raw.notification_type}")
    if raw.date:
        try:
            d = parse_date(raw.date)
            parts.append(f"tarih: {d.strftime('%Y-%m-%d')}")
        except Exception:
            pass
    return " | ".join(parts) + " —"


def build_chunks(raw: RawDoc) -> list[DocumentChunk]:
    date = parse_date(raw.date)
    published_at = parse_date(raw.published_at or raw.date)
    retrieved_at = parse_date(raw.retrieved_at)
    doc_id = raw.doc_id or _chunk_id(f"{raw.ticker}|{raw.url}|{raw.title}")
    source_value = raw.source_type.value
    if source_value == "broker_report":
        source_value = "brokerage"
    notification_type = raw.notification_type or "General Assembly"
    extra_metadata = dict(raw.metadata or {})

    pieces = list(split_text(raw.text))
    # Contextual chunking (Anthropic-style): prepend a context prefix
    # to each chunk so it carries its provenance into the embedding.
    context_prefix = _build_context_prefix(raw, len(pieces))

    output: list[DocumentChunk] = []
    for idx, piece in enumerate(pieces):
        chunk_id = _chunk_id(f"{doc_id}|{idx}")
        piece = f"{context_prefix} {piece}" if context_prefix else piece
        source_channel = str(extra_metadata.get("source_channel", source_value))
        source_reliability = float(extra_metadata.get("source_reliability", raw.confidence))
        author = str(extra_metadata.get("author", ""))
        author_handle = str(extra_metadata.get("author_handle", ""))
        engagement = int(extra_metadata.get("engagement", 0) or 0)
        entity_aliases = list(extra_metadata.get("entity_aliases", []))
        discovered_via = str(extra_metadata.get("discovered_via", ""))
        raw_doc_path = str(extra_metadata.get("raw_doc_path", ""))
        analysis_cache_key = str(extra_metadata.get("analysis_cache_key", ""))
        session_id = str(extra_metadata.get("session_id", ""))
        upload_id = str(extra_metadata.get("upload_id", ""))
        sentiment = score_turkish_financial_sentiment(piece)
        output.append(
            DocumentChunk(
                content=piece,
                ticker=raw.ticker,
                source_type=SourceType(source_value),
                publication_date=published_at,
                date=date,
                institution=raw.institution,
                notification_type=notification_type,
                doc_id=doc_id,
                url=raw.url,
                published_at=published_at,
                retrieved_at=retrieved_at,
                language=raw.language,
                confidence=raw.confidence,
                title=raw.title,
                chunk_id=chunk_id,
                source_channel=source_channel,
                source_reliability=source_reliability,
                author=author,
                author_handle=author_handle,
                engagement=engagement,
                entity_aliases=entity_aliases,
                discovered_via=discovered_via,
                raw_doc_path=raw_doc_path,
                analysis_cache_key=analysis_cache_key,
                sentiment_score=sentiment.score,
                sentiment_label=sentiment.label,
                session_id=session_id,
                upload_id=upload_id,
                metadata={
                    "chunk_index": idx,
                    "chunk_total": len(pieces),
                    "ticker": raw.ticker.upper(),
                    "source_type": source_value,
                    "publication_date": published_at.isoformat(),
                    "institution": raw.institution,
                    "notification_type": notification_type,
                    "url": raw.url,
                    "chunk_id": chunk_id,
                    "ingest_date": retrieved_at.date().isoformat(),
                    "confidence": raw.confidence,
                    "source_channel": source_channel,
                    "source_reliability": source_reliability,
                    "author": author,
                    "author_handle": author_handle,
                    "engagement": engagement,
                    "entity_aliases": entity_aliases,
                    "discovered_via": discovered_via,
                    "raw_doc_path": raw_doc_path,
                    "analysis_cache_key": analysis_cache_key,
                    "sentiment_score": sentiment.score,
                    "sentiment_label": sentiment.label,
                    "sentiment_method": sentiment.method,
                    "session_id": session_id,
                    "upload_id": upload_id,
                    **extra_metadata,
                },
            )
        )
    return output
