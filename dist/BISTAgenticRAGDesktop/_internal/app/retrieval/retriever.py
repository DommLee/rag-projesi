from __future__ import annotations

import time
from collections import deque
from datetime import UTC, datetime
from typing import Any

from app.config import get_settings
from app.retrieval.rerank import rerank_with_time_decay
from app.schemas import DocumentChunk, SourceType
from app.vectorstore.milvus_store import VectorStore


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
            parts.append("source_type in [" + ",".join([s.value for s in source_types]) + "]")
        if as_of_date:
            parts.append(f"date <= {as_of_date.isoformat()}")
        return " AND ".join(parts)

    def retrieve_with_trace(
        self,
        query: str,
        ticker: str,
        source_types: list[SourceType] | None = None,
        as_of_date: datetime | None = None,
        top_k: int | None = None,
    ) -> tuple[list[DocumentChunk], dict[str, Any]]:
        k = top_k or self.settings.max_top_k
        trace = {
            "query": query,
            "ticker": ticker,
            "top_k": k,
            "metadata_filter": self._metadata_filter_expression(ticker, source_types, as_of_date),
            "steps": [],
            "ts": datetime.now(UTC).isoformat(),
        }

        start_search = time.perf_counter()
        docs = self.store.search(
            query=query,
            ticker=ticker,
            source_types=source_types,
            as_of_date=as_of_date,
            top_k=k,
        )
        trace["steps"].append(
            {
                "name": "vector_search",
                "duration_ms": round((time.perf_counter() - start_search) * 1000, 2),
                "items": len(docs),
            }
        )

        start_rerank = time.perf_counter()
        reranked = rerank_with_time_decay(docs)
        trace["steps"].append(
            {
                "name": "time_decay_rerank",
                "duration_ms": round((time.perf_counter() - start_rerank) * 1000, 2),
                "items": len(reranked),
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
    ) -> list[DocumentChunk]:
        docs, _ = self.retrieve_with_trace(query, ticker, source_types, as_of_date, top_k)
        return docs

    def latest_trace(self) -> dict[str, Any]:
        return self.trace_history[-1] if self.trace_history else {}

