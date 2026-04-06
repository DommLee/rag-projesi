from __future__ import annotations

import logging
import time
from collections import Counter, deque
from datetime import UTC, datetime
from typing import Callable

from app.agent.graph import AgentGraph
from app.config import get_settings
from app.evaluation.runner import EvalRuntime
from app.ingestion.kap import KAPIngestor
from app.ingestion.news import NewsIngestor
from app.ingestion.registry import DocumentRegistry
from app.ingestion.report import ReportIngestor
from app.memory.claim_ledger import ClaimLedger
from app.memory.store import MemoryStore
from app.models.providers import RoutedLLM
from app.retrieval.retriever import Retriever
from app.schemas import EvalRequest, EvalResult, IngestRequest, QueryRequest, QueryResponse, SourceType
from app.utils.analytics import broker_bias_lens, disclosure_news_tension_index, narrative_drift_radar
from app.vectorstore.milvus_store import MilvusVectorStore

logger = logging.getLogger(__name__)


class BISTAgentService:
    def __init__(self) -> None:
        self.started_at = datetime.now(UTC)
        self.settings = get_settings()
        self.vector_store = MilvusVectorStore()
        self.retriever = Retriever(self.vector_store)
        self.memory = MemoryStore()
        self.claim_ledger = ClaimLedger()
        self.llm = RoutedLLM()
        self.agent = AgentGraph(self.retriever, self.llm, self.claim_ledger)
        self.document_registry = DocumentRegistry()
        self.latest_eval_result: EvalResult | None = None
        self.last_errors: deque[str] = deque(maxlen=5)
        self.query_latencies_ms: deque[float] = deque(maxlen=500)
        self.last_ingest_stats: dict = {}

        self.metrics = {
            "total_queries": 0,
            "blocked_queries": 0,
            "kap_ingest_chunks": 0,
            "news_ingest_chunks": 0,
            "report_ingest_chunks": 0,
            "ingest_docs_seen": 0,
            "ingest_docs_skipped": 0,
            "last_error": "",
        }

        self.kap_ingestor = KAPIngestor()
        self.news_ingestor = NewsIngestor()
        self.report_ingestor = ReportIngestor()

    def _track_error(self, message: str) -> None:
        self.metrics["last_error"] = message
        self.last_errors.appendleft(f"{datetime.now(UTC).isoformat()} | {message}")

    def _ingest_with_registry(
        self,
        request: IngestRequest,
        collect_fn: Callable[..., list],
        metric_key: str,
        policy_source: object | None = None,
    ) -> int:
        chunks = collect_fn(
            ticker=request.ticker,
            institution=request.institution,
            source_urls=request.source_urls,
            date_from=request.date_from,
            date_to=request.date_to,
        )
        unique_docs_seen = len({(chunk.doc_id, chunk.url) for chunk in chunks})
        raw_chunk_count = len(chunks)

        if request.delta_mode:
            selected, stats = self.document_registry.filter_chunks_for_delta(
                chunks,
                force_reingest=request.force_reingest,
                max_docs=request.max_docs,
            )
        else:
            selected = chunks
            stats = {
                "total_docs_seen": request.max_docs,
                "new": request.max_docs,
                "updated": 0,
                "forced": int(request.force_reingest),
                "skipped": 0,
                "selected_docs": request.max_docs,
                "selected_chunks": len(selected),
                "dedup_rate": 0.0,
            }

        inserted = self.vector_store.upsert(selected)
        policy_summary = getattr(policy_source, "last_policy_summary", {}) if policy_source else {}
        doc_level_stats = {
            "seen": int(stats.get("total_docs_seen", unique_docs_seen)),
            "new": int(stats.get("new", 0)),
            "updated": int(stats.get("updated", 0)),
            "forced": int(stats.get("forced", 0)),
            "skipped": int(stats.get("skipped", 0)),
            "selected": int(stats.get("selected_docs", 0)),
        }
        chunk_level_stats = {
            "raw_chunks": raw_chunk_count,
            "selected_chunks": int(stats.get("selected_chunks", len(selected))),
            "inserted_chunks": inserted,
        }
        self.metrics[metric_key] += inserted
        self.metrics["ingest_docs_seen"] += int(doc_level_stats["seen"])
        self.metrics["ingest_docs_skipped"] += int(doc_level_stats["skipped"])
        self.last_ingest_stats = {
            **stats,
            "doc_level_stats": doc_level_stats,
            "chunk_level_stats": chunk_level_stats,
            "policy_summary": policy_summary,
        }
        return inserted

    def ingest_kap(self, request: IngestRequest) -> int:
        return self._ingest_with_registry(
            request, self.kap_ingestor.collect, "kap_ingest_chunks", policy_source=self.kap_ingestor
        )

    def ingest_news(self, request: IngestRequest) -> int:
        return self._ingest_with_registry(
            request, self.news_ingestor.collect, "news_ingest_chunks", policy_source=self.news_ingestor
        )

    def ingest_report(self, request: IngestRequest) -> int:
        return self._ingest_with_registry(
            request, self.report_ingestor.collect, "report_ingest_chunks", policy_source=self.report_ingestor
        )

    def _update_memory_snapshot(self, ticker: str, response: QueryResponse) -> None:
        now = datetime.now(UTC)
        week_key = f"{now.year}-W{now.isocalendar().week:02d}"
        summary = response.answer_tr[:400]
        themes = [response.consistency_assessment, f"citation_count:{len(response.citations)}"]
        self.memory.upsert_ticker_snapshot(ticker=ticker, week_key=week_key, summary=summary, themes=themes)

    def query(self, request: QueryRequest) -> QueryResponse:
        start = time.perf_counter()
        self.metrics["total_queries"] += 1
        session_ctx = self.memory.get_session(request.session_id)
        state = {
            "ticker": request.ticker,
            "question": request.question,
            "as_of_date": request.as_of_date or datetime.now(UTC),
            "language": request.language or self.settings.default_language,
            "provider_pref": request.provider_pref,
            "session_id": request.session_id,
            "session_ctx": session_ctx,
        }
        try:
            result = self.agent.run(state)
        except Exception as exc:  # noqa: BLE001
            self._track_error(f"query_failed: {exc}")
            raise
        finally:
            self.query_latencies_ms.append((time.perf_counter() - start) * 1000)

        if result.blocked:
            self.metrics["blocked_queries"] += 1
        self.memory.set_session(
            request.session_id,
            {
                "last_ticker": request.ticker,
                "last_question": request.question,
                "last_consistency": result.consistency_assessment,
            },
        )
        self._update_memory_snapshot(request.ticker, result)
        return result

    def eval_run(self, request: EvalRequest) -> EvalResult:
        runner = EvalRuntime(service=self)
        self.latest_eval_result = runner.run(request=request)
        return self.latest_eval_result

    def get_latest_eval_report(self) -> dict:
        if not self.latest_eval_result:
            return {"status": "not_available"}
        return {"status": "ok", "report": self.latest_eval_result.model_dump()}

    def diagnostics(self, ticker: str, as_of_date: datetime | None = None) -> dict:
        chunks = self.retriever.retrieve(
            query=f"{ticker} narrative trend",
            ticker=ticker,
            source_types=[SourceType.KAP, SourceType.NEWS, SourceType.BROKER_REPORT],
            as_of_date=as_of_date,
            top_k=self.settings.max_top_k + 10,
        )
        return {
            "narrative_drift_radar": narrative_drift_radar(chunks),
            "disclosure_news_tension_index": disclosure_news_tension_index(chunks),
            "broker_bias_lens": broker_bias_lens(chunks),
            "claim_ledger": self.claim_ledger.stats(),
            "memory_snapshots": self.memory.get_ticker_snapshots(ticker),
            "retrieval_trace": self.retriever.latest_trace(),
        }

    def health(self) -> dict:
        return {"status": "ok", "time": datetime.now(UTC).isoformat(), "app": self.settings.app_name}

    def ready(self) -> dict:
        return {"status": "ready", "vector_store": self.vector_store.health()}

    def query_with_insight(self, request: QueryRequest) -> dict:
        response = self.query(request)
        source_mix = Counter([citation.source_type.value for citation in response.citations])
        diag = self.diagnostics(request.ticker, request.as_of_date)
        return {
            "response": response.model_dump(),
            "insight": {
                "source_mix": dict(source_mix),
                "citation_count": len(response.citations),
                "ticker_memory_snapshots": len(diag.get("memory_snapshots", {})),
                "tension_index": diag.get("disclosure_news_tension_index", {}).get("tension_index", 0.0),
                "citation_coverage_score": response.citation_coverage_score,
                "evidence_gaps": response.evidence_gaps,
            },
            "diagnostics": diag,
        }

    def get_metrics(self) -> dict:
        uptime = datetime.now(UTC) - self.started_at
        vector_health = self.vector_store.health()
        avg_latency = round(sum(self.query_latencies_ms) / len(self.query_latencies_ms), 2) if self.query_latencies_ms else 0.0
        seen = max(1, self.metrics["ingest_docs_seen"])
        dedup_rate = round(self.metrics["ingest_docs_skipped"] / seen, 4)
        return {
            "uptime_seconds": int(uptime.total_seconds()),
            "runtime_started_at": self.started_at.isoformat(),
            "metrics": self.metrics,
            "vector_store": vector_health,
            "claim_ledger": self.claim_ledger.stats(),
            "milvus_connected": bool(vector_health.get("milvus_connected", False)),
            "fallback_mode": vector_health.get("fallback_mode", "unknown"),
            "ingest_dedup_rate": dedup_rate,
            "avg_retrieval_latency_ms": avg_latency,
            "latest_retrieval_trace": self.retriever.latest_trace(),
            "last_errors": list(self.last_errors),
            "last_ingest_stats": self.last_ingest_stats,
        }
