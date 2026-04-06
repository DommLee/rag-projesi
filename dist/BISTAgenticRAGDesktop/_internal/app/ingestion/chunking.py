from __future__ import annotations

import hashlib
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime

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
    language: str = "tr"
    confidence: float = 0.8
    doc_id: str | None = None


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


def build_chunks(raw: RawDoc) -> list[DocumentChunk]:
    date = parse_date(raw.date)
    published_at = parse_date(raw.published_at or raw.date)
    retrieved_at = parse_date(raw.retrieved_at)
    doc_id = raw.doc_id or _chunk_id(f"{raw.ticker}|{raw.url}|{raw.title}")

    pieces = list(split_text(raw.text))
    output: list[DocumentChunk] = []
    for idx, piece in enumerate(pieces):
        chunk_id = _chunk_id(f"{doc_id}|{idx}")
        output.append(
            DocumentChunk(
                content=piece,
                ticker=raw.ticker,
                source_type=raw.source_type,
                date=date,
                institution=raw.institution,
                doc_id=doc_id,
                url=raw.url,
                published_at=published_at,
                retrieved_at=retrieved_at,
                language=raw.language,
                confidence=raw.confidence,
                title=raw.title,
                chunk_id=chunk_id,
                metadata={
                    "chunk_index": idx,
                    "chunk_total": len(pieces),
                },
            )
        )
    return output
