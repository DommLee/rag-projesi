"""Reranking strategies for retrieved document chunks.

Supports time-decay, source-diversity, and relevance-based reranking.
When a cross-encoder model is available, uses it for semantic reranking;
otherwise falls back to heuristic scoring.
"""

from __future__ import annotations

import logging
import math
from datetime import UTC, datetime

from app.config import get_settings
from app.schemas import DocumentChunk

logger = logging.getLogger(__name__)


def time_decay_score(chunk: DocumentChunk, now: datetime | None = None) -> float:
    """Higher score for more recent documents."""
    now = now or datetime.now(UTC)
    days = max((now - chunk.date).days, 0)
    lam = get_settings().retrieval_time_decay_lambda
    return 1.0 / (1.0 + lam * days)


def source_diversity_bonus(chunk: DocumentChunk, seen_sources: dict[str, int]) -> float:
    """Give a small boost to underrepresented source types."""
    src = chunk.source_type.value
    count = seen_sources.get(src, 0)
    if count == 0:
        return 0.15  # first from this source type
    elif count == 1:
        return 0.05
    return 0.0


def keyword_overlap_score(query: str, chunk: DocumentChunk) -> float:
    """Simple token overlap between query and chunk content."""
    q_tokens = set(query.lower().split())
    c_tokens = set(chunk.content[:500].lower().split())
    if not q_tokens:
        return 0.0
    overlap = len(q_tokens & c_tokens)
    return min(1.0, overlap / max(len(q_tokens), 1))


def rerank_with_time_decay(chunks: list[DocumentChunk]) -> list[DocumentChunk]:
    """Simple time-decay reranking (backward compatible)."""
    return sorted(chunks, key=time_decay_score, reverse=True)


def rerank_advanced(
    chunks: list[DocumentChunk],
    query: str = "",
    *,
    time_weight: float = 0.3,
    diversity_weight: float = 0.2,
    relevance_weight: float = 0.5,
) -> list[DocumentChunk]:
    """Advanced reranking combining time decay, source diversity, and relevance.

    This is a heuristic cross-encoder substitute. When a real cross-encoder
    (e.g. Cohere Rerank) is available, it should be plugged in at the
    ``relevance_weight`` component.
    """
    if not chunks:
        return []

    seen_sources: dict[str, int] = {}
    scored: list[tuple[float, DocumentChunk]] = []

    for chunk in chunks:
        t_score = time_decay_score(chunk)
        d_score = source_diversity_bonus(chunk, seen_sources)
        r_score = keyword_overlap_score(query, chunk) if query else 0.5

        # Reliability bonus: higher-reliability sources get a small boost
        reliability = getattr(chunk, "source_reliability", 0.7)
        r_bonus = (reliability - 0.5) * 0.2  # +/- 0.1
        sentiment_bonus = max(-0.06, min(0.06, float(getattr(chunk, "sentiment_score", 0.0) or 0.0) * 0.06))

        final = (
            time_weight * t_score
            + diversity_weight * d_score
            + relevance_weight * r_score
            + r_bonus
            + sentiment_bonus
        )

        scored.append((final, chunk))
        src = chunk.source_type.value
        seen_sources[src] = seen_sources.get(src, 0) + 1

    scored.sort(key=lambda x: x[0], reverse=True)
    return [chunk for _, chunk in scored]


def try_cross_encoder_rerank(
    query: str,
    chunks: list[DocumentChunk],
    top_k: int = 10,
) -> list[DocumentChunk] | None:
    """Attempt reranking with a cross-encoder model if available.

    Returns None if no cross-encoder is installed, allowing the caller
    to fall back to heuristic reranking.
    """
    settings = get_settings()
    cohere_key = getattr(settings, "cohere_api_key", None)

    if cohere_key:
        try:
            import cohere

            co = cohere.Client(cohere_key)
            texts = [chunk.content[:512] for chunk in chunks]
            response = co.rerank(
                model="rerank-v3.5",
                query=query,
                documents=texts,
                top_n=top_k,
            )
            reranked = [chunks[r.index] for r in response.results]
            logger.info("Cohere rerank applied: %d -> %d docs", len(chunks), len(reranked))
            return reranked
        except Exception as exc:  # noqa: BLE001
            logger.warning("Cohere rerank failed, falling back: %s", exc)

    return None
