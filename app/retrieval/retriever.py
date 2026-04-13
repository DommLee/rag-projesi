from __future__ import annotations

import time
from collections import deque
from datetime import UTC, datetime
from typing import Any

from app.config import get_settings
from app.retrieval.rerank import rerank_advanced, rerank_with_time_decay, try_cross_encoder_rerank
from app.schemas import DocumentChunk, SourceType
from app.vectorstore.types import VectorStore


class Retriever:
    def __init__(self, store: VectorStore) -> None:
        self.store = store
        self.settings = get_settings()
        self.trace_history: deque[dict[str, Any]] = deque(maxlen=self.settings.trace_store_size)

    @staticmethod
    def _metadata_filter_expression(
        ticker: str,
        source_types: list[SourceType] | None,
        as_of_date: datetime | None,
    ) -> str:
        parts = [f'ticker="{ticker.upper()}"']
        if source_types:
            parts.append("source_type in [" + ",".join([f'"{s.value}"' for s in source_types]) + "]")
        if as_of_date:
            parts.append(f"date <= {as_of_date.isoformat()}")
        return " AND ".join(parts)

    @staticmethod
    def _alpha_for_question_type(question_type: str | None) -> float | None:
        """Return hybrid alpha based on structured question_type from intent router.

        Returns ``None`` when question_type is unknown so the caller can
        fall back to the keyword-based heuristic.
        """
        if question_type in ("ticker_lookup", "price_query", "kap_disclosure_types"):
            return 0.3  # BM25-heavy for exact matches
        if question_type in ("thematic", "narrative", "contradiction",
                             "narrative_evolution", "brokerage_narrative"):
            return 0.8  # vector-heavy for semantic
        if question_type in ("consistency_check",):
            return 0.65
        if question_type in ("relationship_query",):
            return 0.5
        return None  # unknown — fall through to keyword heuristic

    def _hybrid_alpha_for_query(
        self,
        query: str,
        source_types: list[SourceType] | None,
        question_type: str | None = None,
    ) -> float:
        # Prefer structured question_type when available
        type_alpha = self._alpha_for_question_type(question_type)
        if type_alpha is not None:
            return type_alpha

        q = query.lower()
        if "kap" in q or (source_types and source_types == [SourceType.KAP]):
            return 0.35
        if any(token in q for token in ["tema", "theme", "narrative", "anlat", "değiş", "degis", "evolution"]):
            return 0.8
        if any(token in q for token in ["çeliş", "celis", "contradict", "align", "tutarlı", "tutarli"]):
            return 0.65
        if any(token in q for token in ["ticker", "bildirim", "rapor", "kaç", "kac", "list", "liste"]):
            return 0.3
        return float(self.settings.weaviate_hybrid_alpha_default)

    def retrieve_with_trace(
        self,
        query: str,
        ticker: str,
        source_types: list[SourceType] | None = None,
        as_of_date: datetime | None = None,
        top_k: int | None = None,
        question_type: str | None = None,
    ) -> tuple[list[DocumentChunk], dict[str, Any]]:
        k = top_k or self.settings.max_top_k
        trace = {
            "query": query,
            "ticker": ticker,
            "top_k": k,
            "metadata_filter": self._metadata_filter_expression(ticker, source_types, as_of_date),
            "steps": [],
            "hybrid_alpha": self._hybrid_alpha_for_query(query, source_types, question_type),
            "question_type": question_type,
            "ts": datetime.now(UTC).isoformat(),
        }

        trace["steps"].append(
            {
                "name": "metadata_first_filter",
                "duration_ms": 0.0,
                "items": 0,
            }
        )
        start_search = time.perf_counter()
        docs = self.store.search(
            query=query,
            ticker=ticker,
            source_types=source_types,
            as_of_date=as_of_date,
            top_k=k,
            alpha=trace["hybrid_alpha"],
        )
        trace["steps"].append(
            {
                "name": "hybrid_vector_search",
                "duration_ms": round((time.perf_counter() - start_search) * 1000, 2),
                "items": len(docs),
            }
        )

        # Reranking pipeline: Cohere cross-encoder when configured, otherwise local heuristic.
        start_rerank = time.perf_counter()
        cross_encoder_result = try_cross_encoder_rerank(query, docs, top_k=k)
        if cross_encoder_result is not None:
            reranked = cross_encoder_result
            rerank_method = "cohere_rerank"
        else:
            reranked = rerank_advanced(docs, query=query)
            rerank_method = "advanced_heuristic"
        trace["steps"].append(
            {
                "name": rerank_method,
                "duration_ms": round((time.perf_counter() - start_rerank) * 1000, 2),
                "items": len(reranked),
                "sentiment_weight_applied": True,
                "cohere_rerank_used": rerank_method == "cohere_rerank",
            }
        )
        self.trace_history.append(trace)
        return reranked, trace

    def retrieve(
        self,
        query: str,
        ticker: str,
        source_types: list[SourceType] | None = None,
        as_of_date: datetime | None = None,
        top_k: int | None = None,
        question_type: str | None = None,
    ) -> list[DocumentChunk]:
        docs, _ = self.retrieve_with_trace(query, ticker, source_types, as_of_date, top_k, question_type)
        return docs

    def latest_trace(self) -> dict[str, Any]:
        return self.trace_history[-1] if self.trace_history else {}
