from __future__ import annotations

from datetime import UTC, datetime

from app.config import get_settings
from app.schemas import DocumentChunk


def time_decay_score(chunk: DocumentChunk, now: datetime | None = None) -> float:
    """
    Higher score for more recent documents.
    """
    now = now or datetime.now(UTC)
    days = max((now - chunk.date).days, 0)
    lam = get_settings().retrieval_time_decay_lambda
    return 1.0 / (1.0 + lam * days)


def rerank_with_time_decay(chunks: list[DocumentChunk]) -> list[DocumentChunk]:
    return sorted(chunks, key=time_decay_score, reverse=True)

