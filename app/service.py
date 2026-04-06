from __future__ import annotations

import logging
import json
import threading
import time
from collections import Counter, deque
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable

from app.agent.graph import AgentGraph
from app.config import get_settings
from app.evaluation.runner import EvalRuntime
from app.ingestion.kap import KAPIngestor
from app.ingestion.news import NewsIngestor
from app.ingestion.registry import DocumentRegistry
from app.ingestion.report import ReportIngestor
from app.ingestion.validation import metadata_snapshot, validate_chunk_contract
from app.memory.claim_ledger import ClaimLedger
from app.memory.store import MemoryStore
from app.market import BISTUniverseService, MarketPriceService
from app.models.providers import RoutedLLM
from app.retrieval.retriever import Retriever
from app.schemas import (
    AutoIngestConfig,
    AutoIngestSource,
    EvalRequest,
    EvalResult,
    IngestRequest,
    QueryRequest,
    QueryResponse,
    SourceType,
)
from app.utils.analytics import broker_bias_lens, disclosure_news_tension_index, narrative_drift_radar
from app.vectorstore.weaviate_store import WeaviateVectorStore

logger = logging.getLogger(__name__)


class BISTAgentService:
    def __init__(self) -> None:
        self.started_at = datetime.now(UTC)
        self.settings = get_settings()
        self.vector_store = WeaviateVectorStore()
        self.retriever = Retriever(self.vector_store)
        self.memory = MemoryStore()
        self.claim_ledger = ClaimLedger()
        self.llm = RoutedLLM()
        self.agent = AgentGraph(self.retriever, self.llm, self.claim_ledger)
        self.document_registry = DocumentRegistry()
        self.universe = BISTUniverseService(self.settings.live_universe_path)
        self.market_prices = MarketPriceService(ttl_seconds=self.settings.live_price_interval_seconds)
        self.latest_eval_result: EvalResult | None = None
        self.last_errors: deque[str] = deque(maxlen=5)
        self.query_latencies_ms: deque[float] = deque(maxlen=500)
        self.last_ingest_stats: dict = {}
        self.auto_ingest_config: AutoIngestConfig = AutoIngestConfig(
            enabled=False,
            interval_minutes=self.settings.auto_ingest_interval_minutes,
            sources=[],
        )
        self._auto_ingest_thread: threading.Thread | None = None
        self._auto_ingest_stop = threading.Event()
        self._auto_ingest_lock = threading.Lock()
        self._auto_ingest_last_run: datetime | None = None
        self._auto_ingest_last_result: dict = {}
        self._channel_last_run: dict[tuple[str, str], datetime] = {}
        self._ticker_activity: Counter[str] = Counter()
        self._ticker_last_seen: dict[str, datetime] = {}

        self.metrics = {
            "total_queries": 0,
            "blocked_queries": 0,
            "kap_ingest_chunks": 0,
            "news_ingest_chunks": 0,
            "report_ingest_chunks": 0,
            "ingest_docs_seen": 0,
            "ingest_docs_skipped": 0,
            "last_error": "",
            "route_direct_count": 0,
            "route_reretrieve_count": 0,
            "route_blocked_count": 0,
        }

        self.kap_ingestor = KAPIngestor()
        self.news_ingestor = NewsIngestor()
        self.report_ingestor = ReportIngestor()
        self.auto_ingest_config = self._load_auto_ingest_config()
        if self.settings.auto_ingest_enabled or self.auto_ingest_config.enabled:
            self.start_auto_ingest()

    def _track_error(self, message: str) -> None:
        self.metrics["last_error"] = message
        self.last_errors.appendleft(f"{datetime.now(UTC).isoformat()} | {message}")

    def _auto_ingest_config_path(self) -> Path:
        return Path(self.settings.auto_ingest_config_path)

    def _default_auto_ingest_config(self) -> AutoIngestConfig:
        return AutoIngestConfig(
            enabled=False,
            interval_minutes=max(1, min(self.settings.auto_ingest_interval_minutes, 5)),
            sources=[
                AutoIngestSource(
                    ticker="ASELS",
                    institution="BIST-Collector",
                    kap_urls=["https://www.kap.org.tr/tr/sirket-bilgileri/genel/209-aselsan-elektronik-sanayi-ve-ticaret-a-s"],
                    news_urls=["https://www.aa.com.tr/tr/rss/default?cat=ekonomi"],
                    report_urls=[],
                    delta_mode=True,
                    max_docs=100,
                )
            ],
        )

    def _load_auto_ingest_config(self) -> AutoIngestConfig:
        path = self._auto_ingest_config_path()
        if not path.exists():
            cfg = self._default_auto_ingest_config()
            self._save_auto_ingest_config(cfg)
            return cfg
        try:
            payload = json.loads(path.read_text(encoding="utf-8-sig"))
            return AutoIngestConfig.model_validate(payload)
        except Exception as exc:  # noqa: BLE001
            self._track_error(f"auto_ingest_config_load_failed: {exc}")
            cfg = self._default_auto_ingest_config()
            self._save_auto_ingest_config(cfg)
            return cfg

    def _save_auto_ingest_config(self, config: AutoIngestConfig) -> None:
        path = self._auto_ingest_config_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(config.model_dump(mode="json", exclude_none=True), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _minutes_since_seen(self, ticker: str) -> float:
        seen = self._ticker_last_seen.get(ticker.upper())
        if not seen:
            return 9999.0
        return max(0.0, (datetime.now(UTC) - seen).total_seconds() / 60.0)

    def _is_channel_due(self, ticker: str, channel: str, interval_seconds: int) -> bool:
        if interval_seconds <= 0:
            return True
        key = (ticker.upper(), channel)
        last = self._channel_last_run.get(key)
        if not last:
            return True
        elapsed = (datetime.now(UTC) - last).total_seconds()
        return elapsed >= interval_seconds

    def _touch_channel(self, ticker: str, channel: str) -> None:
        self._channel_last_run[(ticker.upper(), channel)] = datetime.now(UTC)

    @staticmethod
    def _kap_urls_for_ticker(ticker: str) -> list[str]:
        symbol = ticker.upper()
        return [
            f"https://www.kap.org.tr/tr/sirket-bilgileri/genel/{symbol}",
            f"https://www.kap.org.tr/tr/sirket-bilgileri/ozet/{symbol}",
            f"https://www.kap.org.tr/tr/bildirim-sorgu?symbol={symbol}",
        ]

    @staticmethod
    def _news_urls_for_ticker(ticker: str) -> list[str]:
        symbol = ticker.upper()
        return [
            f"https://news.google.com/rss/search?q={symbol}%20BIST&hl=tr&gl=TR&ceid=TR:tr",
            "https://www.aa.com.tr/tr/rss/default?cat=ekonomi",
        ]

    def _resolve_live_sources(self) -> list[AutoIngestSource]:
        if self.auto_ingest_config.sources:
            return self.auto_ingest_config.sources
        if not self.settings.live_dynamic_universe_enabled:
            return []

        limit = self.settings.live_universe_batch_size
        if not self.settings.kap_api_key:
            limit = min(limit, 12)
        prioritized = self.universe.prioritize(
            limit=limit,
            activity_counter=dict(self._ticker_activity),
            last_seen_minutes={ticker: self._minutes_since_seen(ticker) for ticker in self.universe.list_tickers()},
        )
        sources: list[AutoIngestSource] = []
        for item in prioritized:
            sources.append(
                AutoIngestSource(
                    ticker=item.ticker,
                    institution="BIST-Collector",
                    kap_urls=self._kap_urls_for_ticker(item.ticker),
                    news_urls=self._news_urls_for_ticker(item.ticker),
                    report_urls=[],
                    delta_mode=True,
                    max_docs=80,
                )
            )
        return sources

    def _run_source_ingest_once(self, source: AutoIngestSource) -> dict:
        base = {
            "ticker": source.ticker,
            "institution": source.institution,
            "date_from": source.date_from,
            "date_to": source.date_to,
            "notification_types": source.notification_types,
            "delta_mode": source.delta_mode,
            "max_docs": source.max_docs,
            "force_reingest": source.force_reingest,
        }
        source_result: dict = {"ticker": source.ticker, "institution": source.institution}
        totals = {"inserted_chunks": 0, "channels": {}}

        if source.kap_urls and self._is_channel_due(
            source.ticker, "kap", self.settings.live_kap_interval_seconds
        ):
            inserted = self.ingest_kap(IngestRequest(**base, source_urls=source.kap_urls))
            source_result["kap"] = {"inserted": inserted, "stats": self.last_ingest_stats}
            totals["inserted_chunks"] += inserted
            totals["channels"]["kap"] = "ingested"
            self._touch_channel(source.ticker, "kap")
            self._ticker_activity[source.ticker] += 1
        elif source.kap_urls:
            totals["channels"]["kap"] = "skipped_not_due"

        if source.news_urls and self._is_channel_due(
            source.ticker, "news", self.settings.live_news_interval_seconds
        ):
            inserted = self.ingest_news(IngestRequest(**base, source_urls=source.news_urls))
            source_result["news"] = {"inserted": inserted, "stats": self.last_ingest_stats}
            totals["inserted_chunks"] += inserted
            totals["channels"]["news"] = "ingested"
            self._touch_channel(source.ticker, "news")
            self._ticker_activity[source.ticker] += 1
        elif source.news_urls:
            totals["channels"]["news"] = "skipped_not_due"

        if source.report_urls and self._is_channel_due(
            source.ticker, "report", self.settings.live_report_interval_seconds
        ):
            inserted = self.ingest_report(IngestRequest(**base, source_urls=source.report_urls))
            source_result["report"] = {"inserted": inserted, "stats": self.last_ingest_stats}
            totals["inserted_chunks"] += inserted
            totals["channels"]["report"] = "ingested"
            self._touch_channel(source.ticker, "report")
            self._ticker_activity[source.ticker] += 1
        elif source.report_urls:
            totals["channels"]["report"] = "skipped_not_due"

        if self._is_channel_due(source.ticker, "price", self.settings.live_price_interval_seconds):
            price = self.market_prices.get_price(source.ticker, force_refresh=True)
            source_result["price"] = {
                "ticker": price.ticker,
                "price": price.price,
                "change_pct": price.change_pct,
                "provider": price.provider,
                "stale": price.stale,
                "market_time": price.market_time.isoformat(),
            }
            totals["channels"]["price"] = "refreshed"
            self._touch_channel(source.ticker, "price")
        else:
            totals["channels"]["price"] = "skipped_not_due"

        source_result.update(totals)
        return source_result

    def run_auto_ingest_once(self) -> dict:
        started = datetime.now(UTC)
        sources = self._resolve_live_sources()
        results = []
        total_inserted = 0
        for source in sources:
            try:
                out = self._run_source_ingest_once(source)
                total_inserted += int(out.get("inserted_chunks", 0))
                results.append(out)
            except Exception as exc:  # noqa: BLE001
                err = {"ticker": source.ticker, "error": str(exc)}
                results.append(err)
                self._track_error(f"auto_ingest_source_failed[{source.ticker}]: {exc}")
        finished = datetime.now(UTC)
        report = {
            "started_at": started.isoformat(),
            "finished_at": finished.isoformat(),
            "duration_seconds": round((finished - started).total_seconds(), 2),
            "source_count": len(sources),
            "inserted_chunks_total": total_inserted,
            "dynamic_universe_enabled": self.settings.live_dynamic_universe_enabled,
            "sources": results,
        }
        self._auto_ingest_last_run = finished
        self._auto_ingest_last_result = report
        return report

    def _auto_ingest_loop(self) -> None:
        while not self._auto_ingest_stop.is_set():
            if self.auto_ingest_config.enabled:
                self.run_auto_ingest_once()
            wait_seconds = max(60, int(self.auto_ingest_config.interval_minutes * 60))
            if self._auto_ingest_stop.wait(wait_seconds):
                break

    def start_auto_ingest(self) -> dict:
        with self._auto_ingest_lock:
            if self._auto_ingest_thread and self._auto_ingest_thread.is_alive():
                return self.get_auto_ingest_status()
            self._auto_ingest_stop.clear()
            self._auto_ingest_thread = threading.Thread(target=self._auto_ingest_loop, daemon=True)
            self._auto_ingest_thread.start()
            return self.get_auto_ingest_status()

    def stop_auto_ingest(self) -> dict:
        with self._auto_ingest_lock:
            self._auto_ingest_stop.set()
            if self._auto_ingest_thread and self._auto_ingest_thread.is_alive():
                self._auto_ingest_thread.join(timeout=5)
            return self.get_auto_ingest_status()

    def update_auto_ingest_config(self, config: AutoIngestConfig) -> dict:
        self.auto_ingest_config = config
        self._save_auto_ingest_config(config)
        if config.enabled:
            self.start_auto_ingest()
        else:
            self.stop_auto_ingest()
        return self.get_auto_ingest_status()

    def get_auto_ingest_status(self) -> dict:
        running = bool(self._auto_ingest_thread and self._auto_ingest_thread.is_alive() and not self._auto_ingest_stop.is_set())
        effective_sources = self._resolve_live_sources()
        return {
            "enabled": self.auto_ingest_config.enabled,
            "running": running,
            "interval_minutes": self.auto_ingest_config.interval_minutes,
            "source_count": len(self.auto_ingest_config.sources),
            "effective_source_count": len(effective_sources),
            "dynamic_universe_enabled": self.settings.live_dynamic_universe_enabled,
            "dynamic_universe_batch_size": self.settings.live_universe_batch_size,
            "last_run_at": self._auto_ingest_last_run.isoformat() if self._auto_ingest_last_run else None,
            "last_result": self._auto_ingest_last_result,
            "config_path": str(self._auto_ingest_config_path()),
        }

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
            notification_types=request.notification_types,
        )
        valid_chunks = []
        invalid_chunk_count = 0
        for chunk in chunks:
            ok, issues = validate_chunk_contract(chunk)
            if not ok:
                invalid_chunk_count += 1
                chunk.metadata["contract_issues"] = issues
                continue
            chunk.metadata.update(metadata_snapshot(chunk))
            valid_chunks.append(chunk)

        unique_docs_seen = len({(chunk.doc_id, chunk.url) for chunk in chunks})
        raw_chunk_count = len(valid_chunks)

        if request.delta_mode:
            selected, stats = self.document_registry.filter_chunks_for_delta(
                valid_chunks,
                force_reingest=request.force_reingest,
                max_docs=request.max_docs,
            )
        else:
            selected = valid_chunks
            selected_docs = len({(chunk.doc_id, chunk.url) for chunk in selected})
            stats = {
                "total_docs_seen": unique_docs_seen,
                "new": selected_docs,
                "updated": 0,
                "forced": int(request.force_reingest),
                "skipped": 0,
                "selected_docs": selected_docs,
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
            "invalid_chunk_count": invalid_chunk_count,
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
        self._ticker_activity[request.ticker] += 3
        session_ctx = self.memory.get_session(request.session_id)
        state = {
            "ticker": request.ticker,
            "question": request.question,
            "as_of_date": request.as_of_date or datetime.now(UTC),
            "language": request.language or self.settings.default_language,
            "provider_pref": request.provider_pref,
            "provider_overrides": request.provider_overrides or {},
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
        if result.route_path == "reretrieve":
            self.metrics["route_reretrieve_count"] += 1
        elif result.route_path == "blocked":
            self.metrics["route_blocked_count"] += 1
        else:
            self.metrics["route_direct_count"] += 1
        self._ticker_last_seen[request.ticker] = datetime.now(UTC)
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

    def validate_provider(
        self,
        provider_pref: str | None = None,
        provider_overrides: dict[str, str] | None = None,
        prompt: str = "Reply with a short health confirmation.",
    ) -> dict:
        started = time.perf_counter()
        try:
            text, provider_used = self.llm.generate_with_provider(
                prompt,
                provider_pref=provider_pref,
                provider_overrides=provider_overrides or {},
            )
            latency_ms = round((time.perf_counter() - started) * 1000, 2)
            preview = text.strip().replace("\n", " ")[:200]
            return {
                "ok": True,
                "provider_used": provider_used,
                "latency_ms": latency_ms,
                "preview": preview,
                "error": None,
            }
        except Exception as exc:  # noqa: BLE001
            latency_ms = round((time.perf_counter() - started) * 1000, 2)
            self._track_error(f"provider_validate_failed: {exc}")
            return {
                "ok": False,
                "provider_used": provider_pref or "auto",
                "latency_ms": latency_ms,
                "preview": "",
                "error": str(exc),
            }

    def get_latest_eval_report(self) -> dict:
        if not self.latest_eval_result:
            return {"status": "not_available"}
        return {"status": "ok", "report": self.latest_eval_result.model_dump()}

    def get_ticker_universe(self, limit: int = 50) -> dict:
        prioritized = self.universe.prioritize(
            limit=limit,
            activity_counter=dict(self._ticker_activity),
            last_seen_minutes={ticker: self._minutes_since_seen(ticker) for ticker in self.universe.list_tickers()},
        )
        return {
            "count": len(prioritized),
            "items": [
                {
                    "ticker": item.ticker,
                    "priority_score": item.priority_score,
                    "reason": item.reason,
                }
                for item in prioritized
            ],
        }

    def get_market_prices(self, tickers: list[str] | None = None, limit: int = 12, force_refresh: bool = False) -> dict:
        if not tickers:
            top = self.universe.prioritize(
                limit=limit,
                activity_counter=dict(self._ticker_activity),
                last_seen_minutes={ticker: self._minutes_since_seen(ticker) for ticker in self.universe.list_tickers()},
            )
            tickers = [item.ticker for item in top]
        return self.market_prices.get_prices(tickers=tickers, force_refresh=force_refresh)

    def get_provider_registry(self) -> dict:
        settings = self.settings
        return {
            "defaults": {
                "llm_default": "groq",
                "ollama_model": settings.ollama_model,
                "ollama_base_url": settings.ollama_base_url,
                "embedding_provider": settings.embedding_provider,
                "embedding_model": {
                    "voyage": settings.voyage_embedding_model,
                    "openai": settings.openai_embedding_model,
                    "ollama": settings.ollama_embedding_model,
                    "nomic": settings.nomic_embedding_model,
                },
            },
            "available": {
                "ollama": True,
                "groq": bool(settings.groq_api_key),
                "gemini": bool(settings.gemini_api_key),
                "openai": bool(settings.openai_api_key),
                "together": bool(settings.together_api_key),
            },
        }

    def diagnostics(self, ticker: str, as_of_date: datetime | None = None) -> dict:
        chunks = self.retriever.retrieve(
            query=f"{ticker} narrative trend",
            ticker=ticker,
            source_types=[SourceType.KAP, SourceType.NEWS, SourceType.BROKERAGE],
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
        live_universe = self.get_ticker_universe(limit=min(10, self.settings.live_universe_batch_size))
        return {
            "uptime_seconds": int(uptime.total_seconds()),
            "runtime_started_at": self.started_at.isoformat(),
            "metrics": self.metrics,
            "vector_store": vector_health,
            "claim_ledger": self.claim_ledger.stats(),
            "weaviate_connected": bool(vector_health.get("weaviate_connected", False)),
            "fallback_mode": vector_health.get("fallback_mode", "unknown"),
            "strict_mode": bool(vector_health.get("strict_mode", False)),
            "ingest_dedup_rate": dedup_rate,
            "avg_retrieval_latency_ms": avg_latency,
            "latest_retrieval_trace": self.retriever.latest_trace(),
            "last_errors": list(self.last_errors),
            "last_ingest_stats": self.last_ingest_stats,
            "auto_ingest": self.get_auto_ingest_status(),
            "routing_counters": {
                "direct": self.metrics["route_direct_count"],
                "reretrieve": self.metrics["route_reretrieve_count"],
                "blocked": self.metrics["route_blocked_count"],
            },
            "live_universe_preview": live_universe["items"],
        }
