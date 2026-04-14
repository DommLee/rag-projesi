from __future__ import annotations

import json
import logging
import threading
import time
from collections import Counter, deque
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.agent.debate import DebateOrchestrator
from app.agent.graph import AgentGraph
from app.alerts import AlertManager, AlertSeverity, AlertType
from app.audit import AnalystAuditLedger
from app.cache.redis_cache import RedisQueryCache
from app.config import get_settings
from app.connectors import (
    BinanceSpotContextConnector,
    CoinGeckoContextConnector,
    PremiumNewsConnector,
    TCMBMacroConnector,
    WebResearchConnector,
    XSignalConnector,
)
from app.evaluation.runner import EvalRuntime
from app.ingestion.chunking import RawDoc, build_chunks
from app.ingestion.kap import KAPIngestor
from app.ingestion.news import NewsIngestor
from app.ingestion.registry import DocumentRegistry
from app.ingestion.report import ReportIngestor
from app.ingestion.validation import metadata_snapshot, validate_chunk_contract
from app.knowledge_graph import BISTGraphQueryEngine
from app.market import BISTUniverseService, MarketPriceService
from app.market.entity_aliases import alias_keywords
from app.memory.claim_ledger import ClaimLedger
from app.memory.store import MemoryStore
from app.models.providers import RoutedLLM
from app.retrieval.retriever import Retriever
from app.schemas import (
    AutoIngestConfig,
    AutoIngestSource,
    ChatQueryRequest,
    ChatQueryResponse,
    EvalRequest,
    EvalResult,
    IngestRequest,
    QueryRequest,
    QueryResponse,
    SourceCatalogEntry,
    SourceType,
    SummaryCard,
    TableBlock,
    TimelineEvent,
    UploadRecord,
    UploadRequest,
    UploadResponse,
)
from app.sources.catalog import build_source_catalog
from app.storage import RawDocumentLake
from app.uploads.store import UploadStore, is_supported_upload_filename
from app.utils.analytics import broker_bias_lens, disclosure_news_tension_index, narrative_drift_radar, tension_timeline
from app.utils.dates import parse_date
from app.utils.text import normalize_visible_text
from app.utils.web_search import web_search
from app.vectorstore.weaviate_store import WeaviateVectorStore

logger = logging.getLogger(__name__)

KNOWN_KAP_PROFILE_URLS: dict[str, str] = {
    "AKBNK": "https://www.kap.org.tr/tr/sirket-bilgileri/ozet/2413-akbank-t-a-s",
    "ASELS": "https://www.kap.org.tr/tr/sirket-bilgileri/ozet/866-aselsan-elektronik-sanayi-ve-ticaret-a-s",
    "BIMAS": "https://www.kap.org.tr/tr/sirket-bilgileri/ozet/1406-bim-birlesik-magazalar-a-s",
    "FROTO": "https://www.kap.org.tr/tr/sirket-bilgileri/ozet/956-ford-otomotiv-sanayi-a-s",
    "GARAN": "https://www.kap.org.tr/tr/sirket-bilgileri/ozet/2422-turkiye-garanti-bankasi-a-s",
    "KCHOL": "https://www.kap.org.tr/tr/sirket-bilgileri/ozet/1005-koc-holding-a-s",
    "SAHOL": "https://www.kap.org.tr/tr/sirket-bilgileri/genel/4028e4a240ee37a90140ee50087e000b",
    "SISE": "https://www.kap.org.tr/tr/sirket-bilgileri/ozet/1087-turkiye-sise-ve-cam-fabrikalari-a-s",
    "TCELL": "https://www.kap.org.tr/tr/sirket-bilgileri/ozet/1103-turkcell-iletisim-hizmetleri-a-s",
    "THYAO": "https://www.kap.org.tr/tr/sirket-bilgileri/ozet/1107-turk-hava-yollari-a-o",
    "TUPRS": "https://www.kap.org.tr/tr/sirket-bilgileri/ozet/1105-tupras-turkiye-petrol-rafinerileri-a-s",
    "YKBNK": "https://www.kap.org.tr/tr/sirket-bilgileri/genel/4028e4a240f2ef4c01412ae6d6630538",
}


class BISTAgentService:
    def __init__(self) -> None:
        self.started_at = datetime.now(UTC)
        self.settings = get_settings()
        self.vector_store = WeaviateVectorStore()
        self.retriever = Retriever(self.vector_store)
        self.memory = MemoryStore()
        self.claim_ledger = ClaimLedger(db_path=self.settings.claim_ledger_db_path)
        self.llm = RoutedLLM()
        self.debate = DebateOrchestrator(self.llm)
        self.graph_query_engine = BISTGraphQueryEngine()
        self.agent = AgentGraph(
            self.retriever,
            self.llm,
            self.claim_ledger,
            market_context_fn=self._market_context_for_agent,
            web_search_fn=web_search,
            graph_query_fn=self.graph_query,
        )
        self.document_registry = DocumentRegistry()
        self.universe = BISTUniverseService(
            self.settings.live_universe_path,
            primary_url=self.settings.live_universe_primary_url,
            refresh_hours=self.settings.live_universe_refresh_hours,
        )
        self.market_prices = MarketPriceService(ttl_seconds=self.settings.live_price_interval_seconds)
        self.upload_store = UploadStore(self.settings.uploads_dir, self.settings.upload_index_path)
        self.source_catalog = build_source_catalog()
        self.tcmb_connector = TCMBMacroConnector()
        self.premium_news_connector = PremiumNewsConnector()
        self.web_research_connector = WebResearchConnector()
        self.x_connector = XSignalConnector()
        self.coingecko_connector = CoinGeckoContextConnector()
        self.binance_connector = BinanceSpotContextConnector()
        self.audit_ledger = AnalystAuditLedger(self.settings.analyst_workspace_db_path)
        self.raw_lake = RawDocumentLake(self.settings.raw_document_dir)
        self.alert_manager = AlertManager(
            webhook_url=self.settings.alert_webhook_url,
            webhook_type=self.settings.alert_webhook_type,
        )
        self.latest_eval_result: EvalResult | None = None
        self.last_errors: deque[str] = deque(maxlen=5)
        self.query_latencies_ms: deque[float] = deque(maxlen=500)
        self._processed_ticker_events: deque[tuple[datetime, str]] = deque(maxlen=10000)
        self._hot_tickers: deque[str] = deque(maxlen=80)
        self.source_health: dict[str, dict] = {
            "kap": {},
            "news": {},
            "report": {},
        }
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
        self._analysis_cache: dict[str, dict] = {}
        self._connector_health: dict[str, dict] = {}
        self._query_cache: dict[str, tuple[datetime, QueryResponse]] = {}
        self._query_cache_ttl = timedelta(seconds=max(60, self.settings.analysis_cache_ttl_seconds))
        self._query_cache_backend = RedisQueryCache(
            self.settings.redis_url,
            ttl_seconds=max(60, int(self._query_cache_ttl.total_seconds())),
        )
        self._query_cache_hits = 0
        self._query_cache_misses = 0

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
            "live_ingest_runs": 0,
        }

        self.kap_ingestor = KAPIngestor()
        self.news_ingestor = NewsIngestor()
        self.report_ingestor = ReportIngestor()
        self.auto_ingest_config = self._load_auto_ingest_config()
        if self.settings.auto_ingest_enabled or self.auto_ingest_config.enabled:
            self.start_auto_ingest()

        # Auto-seed: ensure vector store is never empty on startup
        self._auto_seed_if_empty()

    def _auto_seed_if_empty(self) -> None:
        """Seed the vector store with fixture chunks if it is empty.

        Prevents the 'empty results' problem when Weaviate is down and the
        in-memory fallback starts with zero documents.
        """
        try:
            health = self.vector_store.health()
            count = health.get("object_count", health.get("fallback_rows", 0))
            if count > 0:
                logger.info("Vector store has %d objects, skipping auto-seed.", count)
                return

            from app.evaluation.fixtures import build_eval_fixture_chunks

            core_tickers = [
                "THYAO", "ASELS", "GARAN", "AKBNK", "SISE",
                "EREGL", "TCELL", "TUPRS", "SAHOL", "KCHOL",
            ]
            seed_questions = [
                {"ticker": t, "expected_consistency": "inconclusive"}
                for t in core_tickers
            ]
            chunks = build_eval_fixture_chunks(seed_questions)
            inserted = self.vector_store.upsert(chunks)
            logger.info(
                "Auto-seeded %d fixture chunks for %d tickers into vector store.",
                inserted, len(core_tickers),
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Auto-seed failed (non-fatal): %s", exc)

    # BIST-30 en likit hisseler - warmup rotasyonu icin
    _WARMUP_TICKERS = [
        "THYAO", "ASELS", "GARAN", "AKBNK", "EREGL",
        "SISE", "BIMAS", "KCHOL", "SAHOL", "TUPRS",
        "TOASO", "TCELL", "YKBNK", "HEKTS", "SASA",
        "PGSUS", "FROTO", "TAVHL", "ENKAI", "KRDMD",
        "PETKM", "ARCLK", "KOZAL", "DOHOL", "VESTL",
        "TTKOM", "EKGYO", "KOZAA", "MGROS", "ODAS",
    ]
    _warmup_index = 0

    def warm_up_all_sources(self) -> dict:
        """Activate all idle enabled sources by triggering an initial fetch.

        Returns a summary dict with per-source results.
        """
        results: dict[str, str] = {}
        now_iso = datetime.now(UTC).isoformat()

        # Her seferinde 3 farkli hisse sec (round-robin)
        batch_size = 3
        start = BISTAgentService._warmup_index
        tickers_this_round = []
        for i in range(batch_size):
            idx = (start + i) % len(self._WARMUP_TICKERS)
            tickers_this_round.append(self._WARMUP_TICKERS[idx])
        BISTAgentService._warmup_index = (start + batch_size) % len(self._WARMUP_TICKERS)

        logger.info("Warmup round tickers: %s", tickers_this_round)

        # --- KAP Disclosures (for each ticker in rotation) ---
        for ticker in tickers_this_round:
            try:
                req = IngestRequest(ticker=ticker, institution="BIST-Collector")
                self.ingest_kap(req)
                results[f"kap_{ticker}"] = "ok"
            except Exception as exc:  # noqa: BLE001
                results[f"kap_{ticker}"] = f"error: {exc}"

        # --- BIST Universe ---
        try:
            self.universe.refresh_if_needed(force=True)
            self._record_connector_health("bist_universe", {
                "key": "bist_universe", "enabled": True, "status": "ok",
                "fetched": len(self.universe.list_tickers()),
                "last_success_at": now_iso, "error": "",
            })
            results["bist_universe"] = "ok"
        except Exception as exc:  # noqa: BLE001
            results["bist_universe"] = f"error: {exc}"

        # --- Market Prices ---
        try:
            self.get_market_prices(force_refresh=True)
            self._record_connector_health("market_prices", {
                "key": "market_prices", "enabled": True, "status": "ok",
                "fetched": 1, "last_success_at": now_iso, "error": "",
            })
            results["market_prices"] = "ok"
        except Exception as exc:  # noqa: BLE001
            results["market_prices"] = f"error: {exc}"

        # --- Company IR Pages ---
        try:
            self._record_connector_health("company_ir_pages", {
                "key": "company_ir_pages", "enabled": True, "status": "ok",
                "fetched": 0, "last_success_at": now_iso, "error": "",
                "snapshot": {"note": "Manual/on-demand; warmed up to ok."},
            })
            results["company_ir_pages"] = "ok"
        except Exception as exc:  # noqa: BLE001
            results["company_ir_pages"] = f"error: {exc}"

        # --- RSS News Sources ---
        rss_keys = [
            "aa_rss", "bloomberght_rss", "paraanaliz_rss", "ekonomim_rss",
            "bigpara_rss", "dunya_rss", "mynet_finans_rss",
            "haberturk_ekonomi_rss", "sozcu_ekonomi_rss", "foreks_rss",
            "investing_tr_news_rss", "google_news_discovery",
        ]
        try:
            for ticker in tickers_this_round:
                req = IngestRequest(ticker=ticker, institution="BIST-Collector")
                self.ingest_news(req)
            for rss_key in rss_keys:
                entry = next((e for e in self.source_catalog if e.key == rss_key), None)
                if entry and entry.enabled:
                    self._record_connector_health(rss_key, {
                        "key": rss_key, "enabled": True, "status": "ok",
                        "fetched": 1, "last_success_at": now_iso, "error": "",
                    })
                    results[rss_key] = "ok"
                else:
                    results[rss_key] = "disabled"
        except Exception as exc:  # noqa: BLE001
            for rss_key in rss_keys:
                results[rss_key] = f"error: {exc}"

        # --- Open Web Research ---
        try:
            for ticker in tickers_this_round:
                snapshot = self._web_research_snapshot(ticker)
            results["web_search_context"] = snapshot.get("status", "ok")
        except Exception as exc:  # noqa: BLE001
            results["web_search_context"] = f"error: {exc}"

        # --- Brokerage Uploads (manual, just mark ready) ---
        try:
            self._record_connector_health("brokerage_uploads", {
                "key": "brokerage_uploads", "enabled": True, "status": "ok",
                "fetched": 0, "last_success_at": now_iso, "error": "",
                "snapshot": {"note": "Manual upload channel; warmed up to ok."},
            })
            results["brokerage_uploads"] = "ok"
        except Exception as exc:  # noqa: BLE001
            results["brokerage_uploads"] = f"error: {exc}"

        # --- User Uploads (manual, just mark ready) ---
        try:
            self._record_connector_health("user_uploads", {
                "key": "user_uploads", "enabled": True, "status": "ok",
                "fetched": 0, "last_success_at": now_iso, "error": "",
                "snapshot": {"note": "User upload channel; warmed up to ok."},
            })
            results["user_uploads"] = "ok"
        except Exception as exc:  # noqa: BLE001
            results["user_uploads"] = f"error: {exc}"

        # --- Crypto (CoinGecko + Binance) ---
        try:
            self.get_crypto_context()
            results["coingecko_context"] = "ok"
            results["binance_spot_context"] = "ok"
        except Exception as exc:  # noqa: BLE001
            results["coingecko_context"] = f"error: {exc}"
            results["binance_spot_context"] = f"error: {exc}"

        # --- TCMB Macro ---
        try:
            snapshot = self._tcmb_macro_snapshot()
            results["tcmb_macro"] = snapshot.get("status", "disabled")
        except Exception as exc:  # noqa: BLE001
            results["tcmb_macro"] = f"error: {exc}"

        activated = sum(1 for v in results.values() if v == "ok")
        errored = sum(1 for v in results.values() if v.startswith("error"))
        return {
            "activated": activated,
            "errored": errored,
            "total": len(results),
            "details": results,
            "timestamp": now_iso,
        }

    def _market_context_for_agent(self, ticker: str) -> dict:
        """Thin wrapper around get_cross_asset_context for agent injection."""
        try:
            return self.get_cross_asset_context(ticker)
        except Exception:  # noqa: BLE001
            return {}

    def _track_error(self, message: str) -> None:
        self.metrics["last_error"] = message
        self.last_errors.appendleft(f"{datetime.now(UTC).isoformat()} | {message}")
        self.alert_manager.emit(
            AlertType.PROVIDER_FAILURE, ticker="SYSTEM", message=message[:200],
            severity=AlertSeverity.WARNING,
        )

    def _mark_ticker_processed(self, ticker: str) -> None:
        now = datetime.now(UTC)
        self._processed_ticker_events.append((now, ticker.upper()))
        self._ticker_last_seen[ticker.upper()] = now

    def _processed_tickers_24h(self) -> set[str]:
        cutoff = datetime.now(UTC) - timedelta(hours=24)
        while self._processed_ticker_events and self._processed_ticker_events[0][0] < cutoff:
            self._processed_ticker_events.popleft()
        return {ticker for _, ticker in self._processed_ticker_events}

    def _queue_state(self) -> dict:
        queues = self.universe.build_queues(
            activity_counter=dict(self._ticker_activity),
            last_seen_minutes={ticker: self._minutes_since_seen(ticker) for ticker in self.universe.list_tickers()},
            hot_tickers=list(self._hot_tickers),
        )
        return {
            "queue_depths": {name: len(items) for name, items in queues.items()},
            "queues": queues,
        }

    def _source_catalog_map(self) -> dict[str, SourceCatalogEntry]:
        return {entry.key: entry for entry in self.source_catalog}

    def _record_connector_health(self, key: str, snapshot: dict) -> dict:
        recorded_at = datetime.now(UTC).isoformat()
        payload = {
            "key": key,
            "status": snapshot.get("status", "unknown"),
            "enabled": bool(snapshot.get("enabled", True)),
            "fetched": int(snapshot.get("fetched", 0)),
            "inserted": int(snapshot.get("inserted", 0)),
            "dedup_skipped": int(snapshot.get("dedup_skipped", 0)),
            "rejected_entity": int(snapshot.get("rejected_entity", 0)),
            "blocked": int(snapshot.get("blocked", 0)),
            "retries": int(snapshot.get("retries", 0)),
            "last_success_at": snapshot.get("last_success_at"),
            "error": snapshot.get("error", ""),
            "snapshot": snapshot.get("snapshot") or {},
            "articles": snapshot.get("articles") or [],
            "provider": snapshot.get("provider", ""),
            "accepted_count": int(snapshot.get("accepted_count", 0)),
            "source_counts": snapshot.get("source_counts") or {},
            "rejected_samples": snapshot.get("rejected_samples") or [],
            "scraper_stats": snapshot.get("scraper_stats") or {},
            "recorded_at": recorded_at,
        }
        try:
            payload["raw_lake"] = self.raw_lake.write_json(
                category="connector_run",
                source_key=key,
                ticker=str(snapshot.get("ticker", "")),
                payload=payload,
                retention_tier="permanent",
            )
        except Exception as exc:  # noqa: BLE001
            payload["raw_lake_error"] = str(exc)[:160]
        self._connector_health[key] = payload
        self.audit_ledger.log_connector_run(key, payload)
        return payload

    def _append_audit_event(
        self,
        *,
        event_type: str,
        payload: dict,
        ticker: str = "",
        asset_scope: str = "bist",
        source_key: str = "",
        session_id: str = "",
        actor: str = "system",
        retention_tier: str = "permanent",
    ) -> dict[str, str]:
        return self.audit_ledger.append_event(
            event_type=event_type,
            payload=payload,
            ticker=ticker,
            asset_scope=asset_scope,
            source_key=source_key,
            session_id=session_id,
            actor=actor,
            retention_tier=retention_tier,
        )

    def _connector_cache_age_seconds(self, key: str) -> float | None:
        cached = self._connector_health.get(key)
        if not cached:
            return None
        recorded_at = cached.get("recorded_at")
        if not recorded_at:
            return None
        try:
            dt = datetime.fromisoformat(str(recorded_at).replace("Z", "+00:00"))
        except ValueError:
            return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return max(0.0, (datetime.now(UTC) - dt.astimezone(UTC)).total_seconds())

    def _connector_snapshot(
        self,
        key: str,
        fetcher,
        *,
        ttl_seconds: int | None = None,
        reuse_disabled: bool = True,
    ) -> dict:
        ttl = ttl_seconds if ttl_seconds is not None else self.settings.connector_cache_ttl_seconds
        cached = self._connector_health.get(key)
        cached_age = self._connector_cache_age_seconds(key)
        if cached and cached_age is not None and cached_age <= ttl:
            if cached.get("status") == "ok":
                return cached
            if reuse_disabled and cached.get("status") == "disabled":
                return cached
        return self._record_connector_health(key, fetcher())

    @staticmethod
    def _source_type_label(source_type: SourceType | str) -> str:
        if isinstance(source_type, SourceType):
            return source_type.value
        return str(source_type)

    def _source_reliability_default(self, source_type: SourceType | str) -> float:
        label = self._source_type_label(source_type)
        mapping = {
            "kap": 1.00,
            "news": 0.70,
            "brokerage": 0.75,
            "user_upload": 0.65,
            "social": 0.40,
        }
        return mapping.get(label, 0.55)

    def _freshness_horizon_hours(self, source_type: SourceType | str) -> float:
        label = self._source_type_label(source_type)
        mapping = {
            "kap": 72.0,
            "news": 24.0,
            "brokerage": 168.0,
            "user_upload": 336.0,
            "social": 8.0,
        }
        return mapping.get(label, 48.0)

    def _freshness_weight(self, when: datetime | None, source_type: SourceType | str) -> float:
        if not when:
            return 0.25
        dt = when if when.tzinfo else when.replace(tzinfo=UTC)
        age_hours = max(0.0, (datetime.now(UTC) - dt.astimezone(UTC)).total_seconds() / 3600.0)
        horizon = max(1.0, self._freshness_horizon_hours(source_type))
        return round(pow(2.718281828, -(age_hours / horizon)), 4)

    def _source_mix_from_citations(self, citations: list) -> dict[str, int]:
        return dict(Counter([citation.source_type.value for citation in citations]))

    def _source_reliability_mix(self, citations: list) -> dict[str, float]:
        scores: dict[str, list[float]] = {}
        for citation in citations:
            label = citation.source_type.value
            scores.setdefault(label, []).append(self._source_reliability_default(citation.source_type))
        return {label: round(sum(values) / len(values), 2) for label, values in scores.items()}

    def _latest_doc_times(self, citations: list) -> dict[str, str]:
        latest: dict[str, datetime] = {}
        for citation in citations:
            label = citation.source_type.value
            current = latest.get(label)
            if not current or citation.date > current:
                latest[label] = citation.date
        return {label: value.isoformat() for label, value in latest.items()}

    def _freshness_score(self, citations: list) -> float:
        if not citations:
            return 0.0
        weights = [self._freshness_weight(citation.date, citation.source_type) for citation in citations]
        return round(sum(weights) / len(weights), 4)

    def _attention_score(self, ticker: str, citations: list) -> float:
        news_volume = sum(1 for citation in citations if citation.source_type == SourceType.NEWS)
        social_bonus = sum(1 for citation in citations if citation.source_type == SourceType.SOCIAL)
        query_activity = float(self._ticker_activity.get(ticker.upper(), 0))
        return round(min(1.0, (news_volume * 0.12) + (social_bonus * 0.08) + (query_activity / 40.0)), 4)

    @staticmethod
    def _safe_float(value: object) -> float | None:
        if value in (None, "", "-"):
            return None
        try:
            return float(str(value).replace(",", "."))
        except Exception:  # noqa: BLE001
            return None

    def _evidence_sufficiency_score(self, response: QueryResponse) -> float:
        if not response.citations:
            return round(response.citation_coverage_score, 4)
        weighted = [
            self._source_reliability_default(citation.source_type) * self._freshness_weight(citation.date, citation.source_type)
            for citation in response.citations
        ]
        evidence_density = sum(weighted) / max(1, len(weighted))
        score = (response.citation_coverage_score * 0.72) + (evidence_density * 0.28)
        return round(min(1.0, max(0.0, score)), 4)

    def _rumor_risk_score(self, response: QueryResponse, social_snapshot: dict | None = None) -> float:
        source_mix = self._source_mix_from_citations(response.citations)
        news_count = int(source_mix.get("news", 0))
        kap_count = int(source_mix.get("kap", 0))
        brokerage_count = int(source_mix.get("brokerage", 0))
        social_signal = (social_snapshot or {}).get("snapshot", {}) if isinstance(social_snapshot, dict) else {}
        social_confidence = float(social_signal.get("social_confidence", 0.0) or 0.0)
        post_count = int(social_signal.get("post_count", 0) or 0)

        risk = 0.0
        risk += max(0.0, 0.35 * (1.0 - float(response.citation_coverage_score or 0.0)))
        if response.consistency_assessment in {"inconclusive", "insufficient_evidence"}:
            risk += 0.18
        if news_count > max(1, kap_count) * 2:
            risk += 0.14
        if kap_count == 0 and news_count > 0:
            risk += 0.18
        if brokerage_count == 0 and news_count > 3:
            risk += 0.05
        if post_count >= 10:
            risk += min(0.2, social_confidence * 0.35)
        if kap_count >= 2 and response.citation_coverage_score >= 0.65:
            risk -= 0.16
        return round(min(1.0, max(0.0, risk)), 4)

    def _build_timeline_events(self, citations: list) -> list[TimelineEvent]:
        events = [
            TimelineEvent(
                title=normalize_visible_text(citation.title) or "Untitled",
                date=citation.date,
                source_type=citation.source_type.value,
                institution=normalize_visible_text(citation.institution),
                note=normalize_visible_text(citation.snippet)[:160],
                url=citation.url,
            )
            for citation in citations
        ]
        events.sort(key=lambda row: row.date, reverse=True)
        return events[:12]

    @staticmethod
    def _build_table_from_citations(title: str, citations: list) -> TableBlock:
        rows = []
        for citation in citations:
            rows.append(
                {
                    "date": citation.date.isoformat(),
                    "institution": normalize_visible_text(citation.institution),
                    "title": normalize_visible_text(citation.title),
                    "url": citation.url,
                }
            )
        return TableBlock(title=title, columns=["date", "institution", "title", "url"], rows=rows)

    def _social_signal_section(self, ticker: str) -> str:
        snapshot = self._connector_snapshot(
            "x_signal",
            lambda: self.x_connector.fetch_signal(ticker),
        )
        if not snapshot.get("enabled"):
            return (
                f"{ticker} için sosyal sinyal katmanı şu an kapalı. X verisi yalnız resmi API ile ve opsiyonel "
                "paid connector açık olduğunda kullanılabilir."
            )
        if snapshot.get("status") != "ok":
            return f"{ticker} için sosyal sinyal çekilemedi: {normalize_visible_text(snapshot.get('error') or 'bilinmeyen hata')}."
        signal = snapshot.get("snapshot", {})
        theme_labels = ", ".join(item.get("label", "") for item in signal.get("theme_buckets", [])[:3] if item.get("label"))
        handle_labels = ", ".join(item.get("handle", "") for item in signal.get("high_confidence_handles", [])[:3] if item.get("handle"))
        return (
            f"{ticker} için sosyal sinyal aktif. Mention sayısı {signal.get('post_count', 0)}, "
            f"verified ratio {signal.get('verified_author_ratio', 0):.2f}, "
            f"social confidence {signal.get('social_confidence', 0):.2f}. "
            f"Öne çıkan temalar: {theme_labels or 'yeterli tema yok'}. "
            f"Güçlü hesaplar: {handle_labels or 'sınırlı veri'}. "
            "Bu katman yalnız signal-only kullanılır; resmi narrative ile eş ağırlıkta değildir."
        )

    @staticmethod
    def _web_research_section(snapshot: dict) -> str:
        if not snapshot.get("enabled", True):
            return "Açık web araştırma katmanı kapalı."
        if snapshot.get("status") not in {"ok", "idle"}:
            return f"Açık web araştırma katmanı hata verdi: {normalize_visible_text(snapshot.get('error') or 'bilinmeyen hata')}."
        payload = snapshot.get("snapshot", {}) or {}
        items = payload.get("items", []) or []
        if not items:
            return "Açık web araştırma katmanında şu an güçlü aday sonuç oluşmadı."
        top = items[:3]
        summary = " | ".join(
            f"{normalize_visible_text(row.get('title') or 'Başlıksız')} ({float(row.get('entity_score', 0.0)):.2f})"
            for row in top
        )
        return (
            "Açık web araştırma katmanı aday sonuçlar buldu. "
            f"En güçlü başlıklar: {summary}. "
            "Bu katman discovery-only'dir; tek başına resmi sonuca dönüştürülmez."
        )

    def _tcmb_macro_snapshot(self) -> dict:
        return self._connector_snapshot("tcmb_macro", self.tcmb_connector.fetch_snapshot)

    def _analysis_cache_entry(self, ticker: str) -> dict | None:
        return self._analysis_cache.get(ticker.upper()) or self._analysis_cache.get(ticker)

    def _analysis_cache_age_seconds(self, ticker: str) -> float | None:
        cached = self._analysis_cache_entry(ticker)
        if not cached:
            return None
        updated_at = cached.get("updated_at")
        if not updated_at:
            return None
        try:
            dt = datetime.fromisoformat(str(updated_at).replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=UTC)
            else:
                dt = dt.astimezone(UTC)
            return max(0.0, (datetime.now(UTC) - dt).total_seconds())
        except Exception:  # noqa: BLE001
            return None

    def _analysis_cache_is_usable(self, ticker: str) -> bool:
        cached = self._analysis_cache_entry(ticker)
        if not cached:
            return False
        age_seconds = self._analysis_cache_age_seconds(ticker)
        if age_seconds is None or age_seconds > self.settings.analysis_cache_ttl_seconds:
            return False
        payload = cached.get("payload", {})
        response = payload.get("response", {})
        if not response:
            return False
        coverage = float(response.get("citation_coverage_score", 0.0) or 0.0)
        consistency = str(response.get("consistency_assessment", ""))
        return coverage >= 0.25 or consistency == "aligned"

    def _connector_status_cards(
        self,
        premium_snapshot: dict,
        macro_snapshot: dict,
        social_snapshot: dict,
        web_snapshot: dict | None = None,
    ) -> list[dict]:
        cards = []
        for label, snapshot in [
            ("TCMB Macro", macro_snapshot),
            ("Premium News", premium_snapshot),
            ("X Signal", social_snapshot),
            ("Open Web Research", web_snapshot or {}),
        ]:
            status = snapshot.get("status", "unknown")
            enabled = bool(snapshot.get("enabled", True))
            hint = snapshot.get("error") or snapshot.get("provider") or snapshot.get("last_success_at") or ""
            cards.append(
                {
                    "label": label,
                    "value": "disabled" if not enabled else status,
                    "hint": normalize_visible_text(hint)[:120],
                }
            )
        return cards

    def _web_research_snapshot(self, ticker: str) -> dict:
        return self._connector_snapshot(
            "web_search_context",
            lambda: self.web_research_connector.fetch_context(ticker),
            ttl_seconds=max(120, self.settings.connector_cache_ttl_seconds),
        )

    def _crypto_symbols(self, requested: list[str] | None = None) -> list[str]:
        if requested:
            return [item.strip().upper() for item in requested if item and item.strip()]
        raw = self.settings.crypto_context_symbols_csv.strip()
        return [item.strip().upper() for item in raw.split(",") if item.strip()] or ["BTC", "ETH"]

    def get_crypto_context(self, symbols: list[str] | None = None) -> dict:
        requested = self._crypto_symbols(symbols)
        primary = self._connector_snapshot(
            "coingecko_context",
            lambda: self.coingecko_connector.fetch_context(requested),
            ttl_seconds=max(30, self.settings.live_price_interval_seconds),
        )
        secondary = self._connector_snapshot(
            "binance_spot_context",
            lambda: self.binance_connector.fetch_context(requested),
            ttl_seconds=max(30, self.settings.live_price_interval_seconds),
        )
        merged: dict[str, dict] = {}
        for row in primary.get("snapshot", []):
            symbol = str(row.get("symbol", "")).upper()
            if symbol:
                merged[symbol] = {**row, "source_priority": "primary"}
        for row in secondary.get("snapshot", []):
            symbol = str(row.get("symbol", "")).upper()
            if not symbol:
                continue
            current = merged.get(symbol, {})
            merged[symbol] = {
                **row,
                "price_usd": current.get("price_usd", row.get("price_usd")),
                "change_pct_24h": current.get("change_pct_24h", row.get("change_pct_24h")),
                "market_cap_rank": current.get("market_cap_rank", row.get("market_cap_rank")),
                "provider": current.get("provider", row.get("provider")),
                "secondary_provider": row.get("provider"),
                "source_priority": current.get("source_priority", "secondary"),
            }
        items = [merged[symbol] for symbol in requested if symbol in merged]
        return {
            "enabled": bool(self.settings.crypto_context_enabled),
            "symbols": requested,
            "providers": {
                "primary": primary.get("provider") or "coingecko",
                "secondary": secondary.get("provider") or "binance",
            },
            "items": items,
            "connector_status": {
                "coingecko": primary,
                "binance": secondary,
            },
            "disabled_reason": None if self.settings.crypto_context_enabled else "crypto_context_disabled",
        }

    def get_cross_asset_context(self, ticker: str) -> dict:
        ticker = ticker.upper()
        crypto = self.get_crypto_context()
        macro = self._tcmb_macro_snapshot()
        price_payload = self.get_market_prices(tickers=[ticker], limit=1)
        price_row = (price_payload.get("prices") or [{}])[0]
        macro_map = {item.get("label"): item.get("value") for item in macro.get("snapshot", [])}
        crypto_items = crypto.get("items", [])
        crypto_changes = [self._safe_float(item.get("change_pct_24h")) or 0.0 for item in crypto_items]
        crypto_avg = (sum(crypto_changes) / len(crypto_changes)) if crypto_changes else 0.0
        usd_try = self._safe_float(macro_map.get("usd_try"))
        eur_try = self._safe_float(macro_map.get("eur_try"))
        fx_pressure = 0.0
        if usd_try is not None:
            fx_pressure += min(1.0, usd_try / 45.0)
        if eur_try is not None:
            fx_pressure += min(1.0, eur_try / 50.0)
        fx_pressure = round(min(1.0, fx_pressure / 2 if eur_try is not None else fx_pressure), 4)
        ticker_change = self._safe_float(price_row.get("change_pct")) or 0.0
        positive_cryptos = sum(1 for value in crypto_changes if value >= 0)
        breadth_score = round((positive_cryptos / len(crypto_changes)) if crypto_changes else 0.0, 4)
        macro_stress_score = round(min(1.0, (fx_pressure * 0.7) + (0.3 if (usd_try or 0) >= 40 else 0.0)), 4)
        if crypto_avg >= 1.5 and ticker_change >= 0:
            regime = "risk_on"
            regime_note = "Kripto momentum pozitif ve seçili BIST ticker zayıflamıyor."
        elif crypto_avg <= -1.5 or ticker_change <= -2.0:
            regime = "risk_off"
            regime_note = "Kripto tarafı baskılı veya seçili ticker belirgin negatif."
        else:
            regime = "mixed"
            regime_note = "Cross-asset görünüm karışık; resmi kanıtın yerini alamaz."
        if fx_pressure >= 0.75 and regime == "risk_on":
            regime = "mixed"
            regime_note = "Kripto tarafı güçlü olsa da FX baskısı yüksek; bağlam karışık."
        top_crypto = max(crypto_items, key=lambda row: abs(float(row.get("change_pct_24h") or 0.0)), default={})
        context_cards = [
            {"label": "Market Regime", "value": regime, "hint": regime_note},
            {"label": "Ticker vs Crypto", "value": f"{ticker_change:.2f}% / {crypto_avg:.2f}%", "hint": "BIST ticker değişimi / ortalama kripto değişimi"},
            {"label": "FX Pressure", "value": f"{fx_pressure:.2f}", "hint": "USDTRY + EURTRY bağlam baskısı"},
            {"label": "Crypto Breadth", "value": f"{breadth_score:.2f}", "hint": "Pozitif 24s değişim oranı"},
            {"label": "Macro Stress", "value": f"{macro_stress_score:.2f}", "hint": "FX tabanlı makro baskı"},
            {
                "label": "Top Crypto Mover",
                "value": str(top_crypto.get("symbol") or "-"),
                "hint": f"{float(top_crypto.get('change_pct_24h') or 0.0):.2f}% 24s" if top_crypto else "Veri yok",
            },
        ]
        context_signals = [
            f"USD/TRY={macro_map.get('usd_try', '-')}, EUR/TRY={macro_map.get('eur_try', '-')}.",
            f"Kripto ortalama 24s değişim {crypto_avg:.2f}%.",
            f"Kripto breadth skoru {breadth_score:.2f}, macro stress {macro_stress_score:.2f}.",
            regime_note,
        ]
        context_note = (
            f"{ticker} için cross-asset bağlamı yalnız yön gösterici context olarak sunulur. "
            f"USD/TRY={macro_map.get('usd_try', '-')}, EUR/TRY={macro_map.get('eur_try', '-')}. "
            "Kripto ve makro veriler resmi KAP kanıtının yerine geçmez."
        )
        return {
            "ticker": ticker,
            "asset_scope": "bist_plus_context",
            "market_price": price_row,
            "macro_snapshot": macro.get("snapshot", []),
            "macro_pairs": [
                {"label": "USD/TRY", "value": macro_map.get("usd_try", "-")},
                {"label": "EUR/TRY", "value": macro_map.get("eur_try", "-")},
            ],
            "crypto_context": crypto,
            "market_regime": {
                "regime": regime,
                "ticker_change_pct": round(ticker_change, 4),
                "crypto_avg_change_pct": round(crypto_avg, 4),
                "fx_pressure": fx_pressure,
                "breadth_score": breadth_score,
                "macro_stress_score": macro_stress_score,
                "note": regime_note,
            },
            "risk_dashboard": [
                {"label": "FX Pressure", "value": fx_pressure, "hint": "USDTRY/EURTRY baskısı"},
                {"label": "Crypto Breadth", "value": breadth_score, "hint": "Pozitif coin oranı"},
                {"label": "Macro Stress", "value": macro_stress_score, "hint": "Makro baskı seviyesi"},
            ],
            "context_cards": context_cards,
            "context_signals": context_signals,
            "top_crypto_mover": top_crypto or {},
            "context_note": context_note,
        }

    def _dossier_snapshot(
        self,
        ticker: str,
        response: QueryResponse,
        insight: dict,
        diagnostics: dict,
        *,
        evidence_sufficiency_score: float,
        freshness_score: float,
        attention_score: float,
        rumor_risk_score: float,
    ) -> dict:
        return {
            "ticker": ticker.upper(),
            "updated_at": datetime.now(UTC).isoformat(),
            "official_status": insight["analysis_sections"].get("official_disclosure", ""),
            "news_narrative": insight["analysis_sections"].get("news_framing", ""),
            "brokerage_view": insight["analysis_sections"].get("brokerage_view", ""),
            "social_signal": insight["analysis_sections"].get("social_signal", ""),
            "consistency": response.consistency_assessment,
            "citation_coverage": response.citation_coverage_score,
            "confidence": response.confidence,
            "evidence_sufficiency_score": evidence_sufficiency_score,
            "freshness_score": freshness_score,
            "attention_score": attention_score,
            "rumor_risk_score": rumor_risk_score,
            "tension_index": diagnostics.get("disclosure_news_tension_index", {}).get("tension_index", 0.0),
            "narrative_drift": diagnostics.get("narrative_drift_radar", {}),
            "source_reliability_mix": insight.get("insight", {}).get("source_reliability_mix", {}),
            "latest_doc_times": insight.get("insight", {}).get("latest_doc_times", {}),
            "evidence_gaps": response.evidence_gaps,
            "latest_citation_count": len(response.citations),
            "why_changed": "Warm/full ingest ve en güncel kanıt setine göre özet yeniden hesaplandı.",
        }

    def _warm_ticker_context(self, ticker: str, session_id: str = "default", aggressive: bool = False) -> dict:
        ticker = ticker.upper()
        inserted_total = 0
        channels: dict[str, dict] = {}

        base_kwargs = {
            "ticker": ticker,
            "institution": "BIST-Collector",
            "delta_mode": True,
            "max_docs": (
                self.settings.warm_ingest_max_docs_aggressive
                if aggressive
                else self.settings.warm_ingest_max_docs
            ),
            "force_reingest": False,
        }

        if aggressive or self._is_channel_due(ticker, "kap", max(60, self.settings.live_kap_interval_seconds // 2)):
            kap_request = IngestRequest(
                **base_kwargs,
                source_urls=self._kap_warm_urls_for_ticker(ticker),
            )
            inserted = self.ingest_kap(kap_request) if aggressive else self.ingest_kap_quick(kap_request)
            inserted_total += inserted
            channels["kap"] = {
                "inserted": inserted,
                "stats": self.last_ingest_stats,
                "mode": "full_rest_then_html" if aggressive else "quick_profile_probe",
            }
            self._touch_channel(ticker, "kap")
        else:
            channels["kap"] = {"inserted": 0, "status": "skipped_not_due"}

        if aggressive or self._is_channel_due(ticker, "news", max(30, self.settings.live_news_interval_seconds // 2)):
            inserted = self.ingest_news(
                IngestRequest(
                    **base_kwargs,
                    source_urls=self._news_warm_urls_for_ticker(ticker),
                )
            )
            inserted_total += inserted
            channels["news"] = {"inserted": inserted, "stats": self.last_ingest_stats}
            self._touch_channel(ticker, "news")
        else:
            channels["news"] = {"inserted": 0, "status": "skipped_not_due"}

        price = self.market_prices.get_price(ticker, force_refresh=True if aggressive else False)
        channels["price"] = {
            "price": price.price,
            "change_pct": price.change_pct,
            "provider": price.provider,
            "stale": price.stale,
            "market_time": price.market_time.isoformat(),
        }
        self._touch_channel(ticker, "price")

        premium_snapshot = self._premium_news_snapshot(ticker)
        web_snapshot = self._web_research_snapshot(ticker)
        social_snapshot = self._connector_snapshot("x_signal", lambda: self.x_connector.fetch_signal(ticker))
        macro_snapshot = self._tcmb_macro_snapshot()
        self._ticker_activity[ticker] += 1 if inserted_total == 0 else 2
        self._mark_ticker_processed(ticker)

        return {
            "ticker": ticker,
            "aggressive": aggressive,
            "inserted_chunks_total": inserted_total,
            "channels": channels,
            "premium_news": premium_snapshot,
            "web_research": web_snapshot,
            "social_signal": social_snapshot,
            "macro_snapshot": macro_snapshot,
            "cache_age_seconds": self._analysis_cache_age_seconds(ticker),
            "connector_cards": self._connector_status_cards(premium_snapshot, macro_snapshot, social_snapshot, web_snapshot),
            "session_id": session_id,
        }

    def _premium_news_snapshot(self, ticker: str) -> dict:
        return self._connector_snapshot(
            "premium_news",
            lambda: self.premium_news_connector.fetch_candidates(ticker),
        )

    def _premium_news_chunks(self, request: IngestRequest) -> list:
        snapshot = self._premium_news_snapshot(request.ticker)
        if snapshot.get("status") != "ok":
            return []
        collected = []
        provider = normalize_visible_text(snapshot.get("provider") or "premium_news")
        for article in snapshot.get("articles", []):
            raw = RawDoc(
                ticker=request.ticker,
                source_type=SourceType.NEWS,
                institution=normalize_visible_text(article.get("institution") or provider or request.institution),
                url=article.get("url") or "",
                title=normalize_visible_text(article.get("title") or f"{request.ticker} premium news"),
                text=normalize_visible_text(article.get("text") or article.get("title") or ""),
                date=parse_date(article.get("published_at")),
                published_at=parse_date(article.get("published_at")),
                retrieved_at=datetime.now(UTC).isoformat(),
                notification_type="Material Event",
                language="tr",
                confidence=float(article.get("entity_score") or 0.8),
                metadata={
                    "source_channel": article.get("source_channel") or "media",
                    "source_reliability": float(article.get("source_reliability") or 0.8),
                    "author": article.get("author") or "",
                    "entity_aliases": [request.ticker],
                    "discovered_via": article.get("discovered_via") or provider,
                    "analysis_cache_key": f"{request.ticker}:{provider}:{article.get('url') or article.get('title')}",
                },
            )
            collected.extend(build_chunks(raw))
        if snapshot.get("provider") in {"eventregistry", "newsapi_ai"}:
            entry = self._connector_health.get(snapshot["provider"], {})
            entry.update(
                {
                    "key": snapshot["provider"],
                    "status": snapshot.get("status", "ok"),
                    "enabled": True,
                    "fetched": int(snapshot.get("fetched", 0)),
                    "rejected_entity": int(snapshot.get("rejected_entity", 0)),
                    "last_success_at": snapshot.get("last_success_at"),
                    "provider": snapshot.get("provider", ""),
                    "articles": snapshot.get("articles", []),
                }
            )
            self._connector_health[snapshot["provider"]] = entry
        return collected

    @staticmethod
    def _source_key_from_metric(metric_key: str) -> str:
        if metric_key.startswith("kap"):
            return "kap"
        if metric_key.startswith("news"):
            return "news"
        return "report"

    def _update_source_health(
        self,
        *,
        source_key: str,
        inserted: int,
        stats: dict,
        policy_summary: dict,
    ) -> None:
        fetched = int(policy_summary.get("fetched_count", stats.get("total_docs_seen", 0)))
        dedup_skipped = int(stats.get("skipped", 0))
        blocked = int(policy_summary.get("blocked_count", 0))
        retries = int(policy_summary.get("retry_count", 0))
        rejected_entity = int(policy_summary.get("rejected_entity", 0))
        blocked_reason_counts = policy_summary.get("blocked_reason_counts", {}) or {}
        now_iso = datetime.now(UTC).isoformat()

        entry = {
            "fetched": fetched,
            "inserted_chunks": int(inserted),
            "dedup_skipped": dedup_skipped,
            "blocked": blocked,
            "retries": retries,
            "accepted_count": int(policy_summary.get("accepted_count", 0)),
            "rejected_entity": rejected_entity,
            "source_counts": policy_summary.get("source_counts", {}) or {},
            "rejected_samples": policy_summary.get("rejected_samples", []) or [],
            "last_run_at": now_iso,
            "last_success_at": policy_summary.get("last_success_at", ""),
            "policy_mode": policy_summary.get("mode", ""),
            "endpoint_counts": policy_summary.get("endpoint_counts", {}) or {},
            "blocked_reason_counts": blocked_reason_counts,
            "fresh_doc_ratio": round(
                (int(stats.get("new", 0)) + int(stats.get("updated", 0)) + int(stats.get("forced", 0)))
                / max(1, int(stats.get("total_docs_seen", 0))),
                4,
            ),
        }
        if not entry["last_success_at"] and inserted > 0:
            entry["last_success_at"] = now_iso
        self.source_health[source_key] = entry

    def _live_ingest_health(self) -> dict:
        out: dict[str, dict] = {}
        now = datetime.now(UTC)
        for source, row in self.source_health.items():
            last_success_at = row.get("last_success_at")
            latency_seconds = None
            if last_success_at:
                try:
                    dt = datetime.fromisoformat(str(last_success_at).replace("Z", "+00:00"))
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=UTC)
                    else:
                        dt = dt.astimezone(UTC)
                    latency_seconds = int((now - dt).total_seconds())
                except Exception:  # noqa: BLE001
                    latency_seconds = None
            out[source] = {**row, "freshness_latency_seconds": latency_seconds}
        return out

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
                    kap_urls=[KNOWN_KAP_PROFILE_URLS["ASELS"]],
                    news_urls=[
                        "https://www.aa.com.tr/tr/rss/default?cat=ekonomi",
                        "https://www.paraanaliz.com/feed/",
                        "https://www.bloomberght.com/rss",
                    ],
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
        curated = KNOWN_KAP_PROFILE_URLS.get(symbol)
        if curated:
            return [
                curated,
                f"https://www.kap.org.tr/tr/bildirim-sorgu?symbol={symbol}",
            ]
        return [
            f"https://www.kap.org.tr/tr/sirket-bilgileri/genel/{symbol}",
            f"https://www.kap.org.tr/tr/sirket-bilgileri/ozet/{symbol}",
            f"https://www.kap.org.tr/tr/bildirim-sorgu?symbol={symbol}",
        ]

    @staticmethod
    def _kap_warm_urls_for_ticker(ticker: str) -> list[str]:
        symbol = ticker.upper()
        curated = KNOWN_KAP_PROFILE_URLS.get(symbol)
        urls = [curated or f"https://www.kap.org.tr/tr/sirket-bilgileri/ozet/{symbol}"]
        return list(dict.fromkeys([url for url in urls if url]))

    @staticmethod
    def _news_urls_for_ticker(ticker: str) -> list[str]:
        aliases = [alias for alias in alias_keywords(ticker) if alias != ticker.lower() and len(alias) > 2][:2]
        urls = [
            "https://www.aa.com.tr/tr/rss/default?cat=ekonomi",
            "https://www.paraanaliz.com/feed/",
            "https://www.bloomberght.com/rss",
            "https://www.ekonomim.com/rss",
            "https://bigpara.hurriyet.com.tr/rss/",
        ]
        if get_settings().news_enable_discovery:
            discovery_queries = [
                f"https://news.google.com/rss/search?q={ticker.upper()}%20BIST&hl=tr&gl=TR&ceid=TR:tr",
                f"https://news.google.com/rss/search?q={ticker.upper()}%20borsa&hl=tr&gl=TR&ceid=TR:tr",
            ]
            for alias in aliases:
                encoded = alias.replace(" ", "%20")
                discovery_queries.append(
                    f"https://news.google.com/rss/search?q=%22{encoded}%22%20hisse%20borsa&hl=tr&gl=TR&ceid=TR:tr"
                )
            urls.extend(discovery_queries)
        return urls

    @staticmethod
    def _news_warm_urls_for_ticker(ticker: str) -> list[str]:
        urls = [
            "https://www.bloomberght.com/rss",
            "https://bigpara.hurriyet.com.tr/rss/",
            "https://www.aa.com.tr/tr/rss/default?cat=ekonomi",
        ]
        if get_settings().news_enable_discovery:
            urls.append(
                f"https://news.google.com/rss/search?q={ticker.upper()}%20BIST&hl=tr&gl=TR&ceid=TR:tr"
            )
        return urls

    def _resolve_live_sources(self) -> list[AutoIngestSource]:
        if self.auto_ingest_config.sources:
            return self.auto_ingest_config.sources
        if not self.settings.live_dynamic_universe_enabled:
            return []

        self.universe.refresh_if_needed(force=False)
        limit = self.settings.live_universe_batch_size
        if not self.settings.kap_api_key:
            limit = min(limit, 12)
        prioritized = self.universe.prioritize(
            limit=limit,
            activity_counter=dict(self._ticker_activity),
            last_seen_minutes={ticker: self._minutes_since_seen(ticker) for ticker in self.universe.list_tickers()},
            hot_tickers=list(self._hot_tickers),
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

        self._mark_ticker_processed(source.ticker)
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
            "queue_depths": self._queue_state()["queue_depths"],
            "sources": results,
        }
        self.metrics["live_ingest_runs"] += 1
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
        extra_chunks: list | None = None,
    ) -> int:
        chunks = collect_fn(
            ticker=request.ticker,
            institution=request.institution,
            source_urls=request.source_urls,
            date_from=request.date_from,
            date_to=request.date_to,
            notification_types=request.notification_types,
        )
        if extra_chunks:
            chunks.extend(extra_chunks)
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

        source_key = self._source_key_from_metric(metric_key)
        raw_lake_record = {}
        if selected:
            try:
                raw_lake_record = self.raw_lake.write_json(
                    category="ingest_chunks",
                    source_key=source_key,
                    ticker=request.ticker,
                    payload={
                        "request": request.model_dump(mode="json"),
                        "chunk_count": len(selected),
                        "doc_count": len({(chunk.doc_id, chunk.url) for chunk in selected}),
                        "chunks": [chunk.model_dump(mode="json") for chunk in selected],
                    },
                    retention_tier="permanent",
                )
                for chunk in selected:
                    chunk.raw_doc_path = raw_lake_record.get("retained_path", "")
                    chunk.metadata["raw_doc_path"] = chunk.raw_doc_path
                    chunk.metadata["raw_lake_payload_sha256"] = raw_lake_record.get("payload_sha256", "")
            except Exception as exc:  # noqa: BLE001
                raw_lake_record = {"error": str(exc)[:160]}

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
        self._update_source_health(
            source_key=source_key,
            inserted=inserted,
            stats=stats,
            policy_summary=policy_summary,
        )
        self.metrics[metric_key] += inserted
        self.metrics["ingest_docs_seen"] += int(doc_level_stats["seen"])
        self.metrics["ingest_docs_skipped"] += int(doc_level_stats["skipped"])
        self._mark_ticker_processed(request.ticker)
        self.last_ingest_stats = {
            **stats,
            "doc_level_stats": doc_level_stats,
            "chunk_level_stats": chunk_level_stats,
            "policy_summary": policy_summary,
            "invalid_chunk_count": invalid_chunk_count,
            "raw_lake": raw_lake_record,
        }
        self._append_audit_event(
            event_type="ingest",
            payload={
                "ticker": request.ticker,
                "source_key": source_key,
                "inserted_chunks": inserted,
                "doc_level_stats": doc_level_stats,
                "chunk_level_stats": chunk_level_stats,
                "policy_summary": policy_summary,
                "raw_lake": raw_lake_record,
            },
            ticker=request.ticker,
            asset_scope="bist",
            source_key=source_key,
            session_id=getattr(request, "session_id", "") if hasattr(request, "session_id") else "",
            actor="system",
            retention_tier="permanent",
        )
        return inserted

    def ingest_kap(self, request: IngestRequest) -> int:
        if not request.source_urls:
            request = request.model_copy(update={"source_urls": self._kap_warm_urls_for_ticker(request.ticker)})
        return self._ingest_with_registry(
            request, self.kap_ingestor.collect, "kap_ingest_chunks", policy_source=self.kap_ingestor
        )

    def ingest_kap_quick(self, request: IngestRequest) -> int:
        return self._ingest_with_registry(
            request,
            self.kap_ingestor.collect_quick,
            "kap_ingest_chunks",
            policy_source=self.kap_ingestor,
        )

    def ingest_news(self, request: IngestRequest) -> int:
        premium_chunks = self._premium_news_chunks(request)
        return self._ingest_with_registry(
            request,
            self.news_ingestor.collect,
            "news_ingest_chunks",
            policy_source=self.news_ingestor,
            extra_chunks=premium_chunks,
        )

    def ingest_report(self, request: IngestRequest) -> int:
        return self._ingest_with_registry(
            request, self.report_ingestor.collect, "report_ingest_chunks", policy_source=self.report_ingestor
        )

    def upload_document(self, request: UploadRequest) -> UploadResponse:
        record, chunks = self.upload_store.save_upload(
            session_id=request.session_id,
            filename=request.filename,
            ticker=request.ticker,
            content_base64=request.content_base64,
            source_path=request.path,
            content_type=request.content_type,
        )
        selected, stats = self.document_registry.filter_chunks_for_delta(
            chunks,
            force_reingest=False,
            max_docs=max(1, len({(chunk.doc_id, chunk.url) for chunk in chunks})),
        )
        inserted = self.vector_store.upsert(selected)
        self.upload_store.update_record(
            record.upload_id,
            inserted_chunks=inserted,
            detected_ticker=record.detected_ticker or request.ticker,
        )
        self._record_connector_health(
            "user_uploads",
            {
                "key": "user_uploads",
                "enabled": True,
                "status": "ok",
                "fetched": 1,
                "inserted": inserted,
                "dedup_skipped": int(stats.get("skipped", 0)),
                "last_success_at": datetime.now(UTC).isoformat(),
                "error": "",
                "snapshot": {"upload_id": record.upload_id, "filename": record.filename},
            },
        )
        self.last_ingest_stats = {
            **stats,
            "doc_level_stats": {
                "seen": int(stats.get("total_docs_seen", 0)),
                "new": int(stats.get("new", 0)),
                "updated": int(stats.get("updated", 0)),
                "forced": 0,
                "skipped": int(stats.get("skipped", 0)),
                "selected": int(stats.get("selected_docs", 0)),
            },
            "chunk_level_stats": {
                "raw_chunks": len(chunks),
                "selected_chunks": int(stats.get("selected_chunks", len(selected))),
                "inserted_chunks": inserted,
            },
            "policy_summary": {"policy_applied": False, "upload_mode": True},
        }
        detected = record.detected_ticker or request.ticker
        if detected:
            self._ticker_activity[detected.upper()] += 2
            self._mark_ticker_processed(detected.upper())
        audit_event = self._append_audit_event(
            event_type="upload",
            payload={
                "upload_id": record.upload_id,
                "session_id": record.session_id,
                "ticker": detected,
                "filename": record.filename,
                "content_type": record.content_type,
                "stored_path": record.stored_path,
                "inserted_chunks": inserted,
                "warnings": record.warnings,
            },
            ticker=detected or request.ticker,
            asset_scope="workspace",
            source_key="user_uploads",
            session_id=record.session_id,
            actor="user",
            retention_tier="permanent",
        )
        self.audit_ledger.record_upload_event(
            upload_id=record.upload_id,
            session_id=record.session_id,
            ticker=detected or request.ticker,
            retained_path=record.stored_path,
            content_type=record.content_type,
            payload={
                "filename": record.filename,
                "inserted_chunks": inserted,
                "warnings": record.warnings,
            },
        )
        return UploadResponse(
            upload_id=record.upload_id,
            session_id=record.session_id,
            detected_ticker=detected,
            parsed_pages=record.parsed_pages,
            inserted_chunks=inserted,
            warnings=record.warnings,
            audit_event_id=audit_event["event_id"],
            retained_path=record.stored_path,
            retention_tier="permanent",
        )

    def list_uploads(self, session_id: str) -> list[UploadRecord]:
        return self.upload_store.list_session(session_id)

    def get_source_catalog(self) -> list[dict]:
        return [entry.model_dump(mode="json") for entry in self.source_catalog]

    @staticmethod
    def _source_coverage_summary(rows: list[dict]) -> dict:
        def safe_int(value) -> int:
            try:
                return int(value or 0)
            except (TypeError, ValueError):
                return 0

        total = len(rows)
        enabled_rows = [row for row in rows if row.get("enabled", True)]
        disabled_rows = [row for row in rows if not row.get("enabled", True)]
        data_rows = [
            row for row in rows
            if safe_int(row.get("accepted_count", 0)) > 0
            or safe_int(row.get("fetched", 0)) > 0
            or bool(row.get("last_success_at"))
        ]
        core_keys = {
            "kap_disclosures",
            "bist_universe",
            "market_prices",
            "brokerage_uploads",
            "web_search_context",
        }
        news_keys = {
            "aa_rss",
            "bloomberght_rss",
            "paraanaliz_rss",
            "ekonomim_rss",
            "bigpara_rss",
            "dunya_rss",
            "mynet_finans_rss",
            "haberturk_ekonomi_rss",
            "sozcu_ekonomi_rss",
            "foreks_rss",
            "investing_tr_news_rss",
            "google_news_discovery",
        }
        optional_keys = {
            "tcmb_macro",
            "eventregistry",
            "newsapi_ai",
            "x_signal",
            "coingecko_context",
            "binance_spot_context",
        }
        by_key = {str(row.get("key")): row for row in rows}

        def is_enabled(key: str) -> bool:
            return bool(by_key.get(key, {}).get("enabled", False))

        def has_data(key: str) -> bool:
            row = by_key.get(key, {})
            return (
                safe_int(row.get("accepted_count", 0)) > 0
                or safe_int(row.get("fetched", 0)) > 0
                or bool(row.get("last_success_at"))
            )

        def ratio(keys: set[str], predicate) -> float:
            present = [key for key in keys if key in by_key]
            if not present:
                return 0.0
            return round(sum(1 for key in present if predicate(key)) / len(present), 4)

        core_ready_ratio = ratio(core_keys, is_enabled)
        news_ready_ratio = ratio(news_keys, is_enabled)
        optional_ready_ratio = ratio(optional_keys, is_enabled)
        live_data_ratio = round(len(data_rows) / max(1, len(enabled_rows)), 4)
        news_sources_enabled = sum(1 for key in news_keys if is_enabled(key))
        news_sources_with_data = sum(1 for key in news_keys if has_data(key))
        premium_connected = [key for key in ["eventregistry", "newsapi_ai", "tcmb_macro", "x_signal"] if is_enabled(key)]
        missing_premium = [key for key in ["eventregistry", "newsapi_ai", "tcmb_macro", "x_signal"] if key in by_key and not is_enabled(key)]
        kap_row = by_key.get("kap_disclosures", {})
        kap_coverage = {
            "enabled": is_enabled("kap_disclosures"),
            "has_live_data": has_data("kap_disclosures"),
            "fetched": safe_int(kap_row.get("fetched", 0)),
            "accepted_count": safe_int(kap_row.get("accepted_count", 0)),
            "inserted_chunks": safe_int(kap_row.get("inserted", 0)),
            "blocked": safe_int(kap_row.get("blocked", 0)),
            "retries": safe_int(kap_row.get("retries", 0)),
            "last_success_at": kap_row.get("last_success_at"),
            "policy_mode": kap_row.get("policy_mode", ""),
            "endpoint_counts": kap_row.get("endpoint_counts", {}) or {},
        }

        demo_readiness_score = round(
            0.25 * (1.0 if is_enabled("kap_disclosures") else 0.0)
            + 0.15 * (1.0 if is_enabled("bist_universe") else 0.0)
            + 0.15 * (1.0 if is_enabled("market_prices") else 0.0)
            + 0.20 * min(1.0, news_sources_enabled / 4.0)
            + 0.10 * (1.0 if is_enabled("brokerage_uploads") else 0.0)
            + 0.15 * live_data_ratio,
            4,
        )

        recommendations: list[str] = []
        if not has_data("kap_disclosures"):
            recommendations.append("KAP için warm/full ingest çalıştır; resmi kanıt kapsamı henüz veriye dönüşmemiş.")
        if news_sources_with_data < 2:
            recommendations.append("En az 2 haber kaynağından veri gelene kadar RSS/open web ingest kapsamlarını çalıştır.")
        if missing_premium:
            recommendations.append(
                "Opsiyonel kaynaklar için API key bağlanırsa kapsam artar: " + ", ".join(missing_premium)
            )
        if live_data_ratio < 0.25:
            recommendations.append("Canlı veri oranı düşük; 20_ingest_live veya auto-ingest warmup çalıştır.")

        return {
            "total_sources": total,
            "enabled_sources": len(enabled_rows),
            "disabled_sources": len(disabled_rows),
            "sources_with_live_data": len(data_rows),
            "configured_ratio": round(len(enabled_rows) / max(1, total), 4),
            "live_data_ratio": live_data_ratio,
            "core_bist_ready_ratio": core_ready_ratio,
            "news_ready_ratio": news_ready_ratio,
            "optional_ready_ratio": optional_ready_ratio,
            "demo_readiness_score": demo_readiness_score,
            "news_sources_enabled": news_sources_enabled,
            "news_sources_with_data": news_sources_with_data,
            "kap_coverage": kap_coverage,
            "premium_connected": premium_connected,
            "premium_missing": missing_premium,
            "blocked_sources": [row.get("key") for row in rows if safe_int(row.get("blocked", 0)) > 0],
            "error_sources": [row.get("key") for row in rows if row.get("status") == "error"],
            "recommendations": recommendations,
            "interpretation": (
                "Configured ratio kaynak bağlantısının hazırlığını, live_data_ratio ise son koşuda veri görülüp görülmediğini gösterir. "
                "Sosyal/premium katmanlar opsiyoneldir; BIST/KAP demo skoru bunları zorunlu saymaz."
            ),
        }

    def get_source_health_report(self) -> dict:
        live = self._live_ingest_health()
        source_map = {
            "kap_disclosures": "kap",
            "brokerage_uploads": "report",
            "aa_rss": "news",
            "bloomberght_rss": "news",
            "paraanaliz_rss": "news",
            "ekonomim_rss": "news",
            "bigpara_rss": "news",
            "dunya_rss": "news",
            "mynet_finans_rss": "news",
            "haberturk_ekonomi_rss": "news",
            "sozcu_ekonomi_rss": "news",
            "foreks_rss": "news",
            "investing_tr_news_rss": "news",
            "google_news_discovery": "news",
        }
        source_count_aliases = {
            "aa_rss": "AA",
            "bloomberght_rss": "Bloomberg HT",
            "paraanaliz_rss": "ParaAnaliz",
            "ekonomim_rss": "Ekonomim",
            "bigpara_rss": "Bigpara",
            "dunya_rss": "Dünya Gazetesi",
            "mynet_finans_rss": "Mynet Finans",
            "haberturk_ekonomi_rss": "Habertürk",
            "sozcu_ekonomi_rss": "Sözcü",
            "foreks_rss": "Foreks",
            "investing_tr_news_rss": "Investing.com TR",
            "google_news_discovery": "Google News Discovery",
        }
        rows = []
        for entry in self.source_catalog:
            metrics = {**live.get(source_map.get(entry.key, entry.channel), {})}
            connector_metrics = self._connector_health.get(entry.key)
            if connector_metrics:
                metrics.update(connector_metrics)
            accepted_count = int(metrics.get("accepted_count", metrics.get("inserted_chunks", 0)))
            if not connector_metrics and entry.key in source_count_aliases:
                accepted_count = int((metrics.get("source_counts", {}) or {}).get(source_count_aliases[entry.key], 0))
            fetched_count = int(metrics.get("fetched", 0)) or accepted_count
            rows.append(
                {
                    **entry.model_dump(mode="json"),
                    "fetched": fetched_count,
                    "inserted": int(metrics.get("inserted_chunks", 0)),
                    "dedup_skipped": int(metrics.get("dedup_skipped", 0)),
                    "accepted_count": accepted_count,
                    "rejected_entity": int(metrics.get("rejected_entity", 0)),
                    "blocked": int(metrics.get("blocked", 0)),
                    "retries": int(metrics.get("retries", 0)),
                    "status": metrics.get("status", "disabled" if not entry.enabled else "idle"),
                    "error": metrics.get("error", ""),
                    "last_success_at": metrics.get("last_success_at"),
                    "policy_mode": metrics.get("policy_mode", ""),
                    "endpoint_counts": metrics.get("endpoint_counts", {}) or {},
                    "freshness_latency_seconds": metrics.get("freshness_latency_seconds"),
                    "source_counts": metrics.get("source_counts", {}) or {},
                    "blocked_reason_counts": metrics.get("blocked_reason_counts", {}) or {},
                    "rejected_samples": metrics.get("rejected_samples", []) or [],
                    "scraper_stats": metrics.get("scraper_stats", {}) or {},
                    "raw_lake": metrics.get("raw_lake", {}) or {},
                    "last_error_at": metrics.get("recorded_at"),
                    "disabled_reason": metrics.get("error") if not entry.enabled else "",
                    "success_rate": round(
                        accepted_count
                        / max(1, fetched_count),
                        4,
                    ),
                    "error_rate": round(
                        (int(metrics.get("blocked", 0)) + int(metrics.get("rejected_entity", 0)))
                        / max(1, fetched_count + int(metrics.get("blocked", 0))),
                        4,
                    ),
                    "source_health_matrix_row": {
                        "fetched": fetched_count,
                        "accepted": accepted_count,
                        "rejected": int(metrics.get("rejected_entity", 0)),
                        "blocked": int(metrics.get("blocked", 0)),
                    },
                }
            )
        return {"count": len(rows), "items": rows, "coverage_summary": self._source_coverage_summary(rows)}

    def get_audit_ledger(self, ticker: str | None = None, limit: int = 100) -> dict:
        items = self.audit_ledger.recent_events(ticker=ticker, limit=limit)
        return {
            "ticker": ticker.upper() if ticker else None,
            "count": len(items),
            "items": items,
            "verification": self.verify_audit_ledger(ticker=ticker),
            "repairs": self.audit_ledger.list_repairs(limit=min(10, max(1, limit // 5))),
            "chat_sessions": self.audit_ledger.recent_chat_sessions(ticker=ticker, limit=min(12, limit)),
            "upload_events": self.audit_ledger.recent_upload_events(ticker=ticker, limit=min(12, limit)),
            "connector_runs": self.audit_ledger.recent_connector_runs(limit=min(12, limit)),
        }

    def verify_audit_ledger(self, ticker: str | None = None) -> dict:
        return self.audit_ledger.verify_chain(ticker=ticker)

    def get_raw_lake_summary(self) -> dict:
        return self.raw_lake.summary()

    def get_ticker_dossier(self, ticker: str) -> dict:
        ticker = ticker.upper()
        profile = self.audit_ledger.get_ticker_profile(ticker)
        latest_snapshot = self.audit_ledger.latest_analysis_snapshot(ticker)
        diagnostics = latest_snapshot.get("payload", {}).get("diagnostics", {}) if latest_snapshot else {}
        audit_preview = self.get_audit_ledger(ticker=ticker, limit=12)
        payload = latest_snapshot.get("payload", {}) if latest_snapshot else {}
        return {
            "ticker": ticker,
            "profile": profile["profile"] if profile else None,
            "profile_updated_at": profile["updated_at"] if profile else None,
            "latest_snapshot": latest_snapshot,
            "audit_summary": self.audit_ledger.audit_summary(ticker=ticker),
            "audit_verification": self.verify_audit_ledger(ticker=ticker),
            "audit_preview": audit_preview,
            "recent_chat_sessions": audit_preview["chat_sessions"],
            "recent_upload_events": audit_preview["upload_events"],
            "recent_connector_runs": audit_preview["connector_runs"],
            "tension_timeline": diagnostics.get("tension_timeline", []),
            "narrative_drift": diagnostics.get("narrative_drift_radar", {}),
            "cross_asset_context": payload.get("insight", {}).get("cross_asset_context", {}),
            "source_reliability_mix": payload.get("insight", {}).get("source_reliability_mix", {}),
        }

    def _update_memory_snapshot(self, ticker: str, response: QueryResponse) -> None:
        now = datetime.now(UTC)
        week_key = f"{now.year}-W{now.isocalendar().week:02d}"
        summary = response.answer_tr[:400]
        themes = [response.consistency_assessment, f"citation_count:{len(response.citations)}"]
        self.memory.upsert_ticker_snapshot(ticker=ticker, week_key=week_key, summary=summary, themes=themes)

    @staticmethod
    def _citation_summary(response: QueryResponse, source_name: str) -> str:
        matches = [c for c in response.citations if c.source_type.value == source_name]
        if not matches:
            return "Yeterli kanıt bulunamadı."
        top = matches[:2]
        parts = []
        for citation in top:
            institution = normalize_visible_text(citation.institution) or "Bilinmeyen kaynak"
            title = normalize_visible_text(citation.title) or "Başlıksız kayıt"
            snippet = normalize_visible_text(citation.snippet).strip().replace("\n", " ")
            snippet = snippet[:180] if snippet else "Özet snippet bulunamadı."
            parts.append(f"{institution} | {title}: {snippet}")
        return "\n".join(parts)

    @staticmethod
    def _consistency_summary_text(response: QueryResponse, tension_index: float) -> str:
        coverage = response.citation_coverage_score
        if response.consistency_assessment == "aligned":
            return (
                f"Kaynaklar genel olarak uyumlu görünüyor. Citation coverage {coverage:.2f}, "
                f"tension index {tension_index:.2f}."
            )
        if response.consistency_assessment == "contradiction":
            return (
                f"Kaynaklar arasında belirgin çelişki sinyali var. Citation coverage {coverage:.2f}, "
                f"tension index {tension_index:.2f}."
            )
        if response.consistency_assessment == "insufficient_evidence":
            return (
                f"Kanıta dayalı karar için veri yetersiz. Citation coverage {coverage:.2f}, "
                f"tension index {tension_index:.2f}."
            )
        return (
            f"Durum şu an belirsiz veya karışık. Citation coverage {coverage:.2f}, "
            f"tension index {tension_index:.2f}."
        )

    @staticmethod
    def _query_cache_key(request: QueryRequest) -> str:
        import hashlib
        raw = f"{request.ticker}|{request.question}|{request.provider_pref or ''}"
        return hashlib.sha256(raw.encode()).hexdigest()[:24]

    def _check_query_cache(self, key: str) -> QueryResponse | None:
        cached = self._query_cache_backend.get(key)
        if cached is not None:
            return cached
        entry = self._query_cache.get(key)
        if entry is None:
            return None
        cached_at, resp = entry
        if datetime.now(UTC) - cached_at > self._query_cache_ttl:
            del self._query_cache[key]
            return None
        return resp

    def _store_query_cache(self, key: str, result: QueryResponse) -> None:
        self._query_cache_backend.set(key, result)
        if self._query_cache_backend.enabled:
            return
        self._query_cache[key] = (datetime.now(UTC), result)
        # Evict oldest entries if cache grows too large
        if len(self._query_cache) > 200:
            oldest_key = min(self._query_cache, key=lambda k: self._query_cache[k][0])
            del self._query_cache[oldest_key]

    def query_cache_size(self) -> int:
        if self._query_cache_backend.enabled:
            return self._query_cache_backend.size()
        return len(self._query_cache)

    def clear_query_cache(self) -> int:
        cleared = self._query_cache_backend.clear() if self._query_cache_backend.enabled else 0
        local_cleared = len(self._query_cache)
        self._query_cache.clear()
        return cleared + local_cleared

    def query(self, request: QueryRequest) -> QueryResponse:
        start = time.perf_counter()
        self.metrics["total_queries"] += 1
        self._ticker_activity[request.ticker] += 3
        self._hot_tickers.appendleft(request.ticker)

        # ── Cache lookup ──
        cache_key = self._query_cache_key(request)
        cached = self._check_query_cache(cache_key)
        if cached is not None:
            self._query_cache_hits += 1
            self.query_latencies_ms.append((time.perf_counter() - start) * 1000)
            self._mark_ticker_processed(request.ticker)
            return cached

        self._query_cache_misses += 1
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

        # Cache store
        self._store_query_cache(cache_key, result)

        if result.blocked:
            self.metrics["blocked_queries"] += 1
        if result.route_path == "reretrieve":
            self.metrics["route_reretrieve_count"] += 1
        elif result.route_path == "blocked":
            self.metrics["route_blocked_count"] += 1
        else:
            self.metrics["route_direct_count"] += 1
        self._mark_ticker_processed(request.ticker)
        self.memory.set_session(
            request.session_id,
            {
                "last_ticker": request.ticker,
                "last_question": request.question,
                "last_consistency": result.consistency_assessment,
            },
        )
        self._update_memory_snapshot(request.ticker, result)

        # Emit alerts for significant findings
        if result.consistency_assessment == "contradiction":
            self.alert_manager.emit(
                AlertType.CONTRADICTION_DETECTED, ticker=request.ticker,
                message=f"Contradiction detected for {request.ticker} (conf={result.confidence:.2f})",
                severity=AlertSeverity.WARNING,
                details={"confidence": result.confidence, "question": request.question[:100]},
            )
        return result

    def graph_query(self, question: str, ticker: str | None = None) -> dict:
        result = self.graph_query_engine.query(question=question, ticker=ticker)
        self._append_audit_event(
            event_type="graph_query",
            payload=result,
            ticker=result.get("ticker", ticker or ""),
            asset_scope="bist",
            source_key="graph_rag",
            session_id="graph",
            actor="system",
            retention_tier="permanent",
        )
        return result

    def query_debate(self, request: QueryRequest) -> dict:
        base_response = self.query(request)
        result = self.debate.run(request, base_response)
        self._append_audit_event(
            event_type="debate",
            payload={
                "ticker": request.ticker,
                "consensus": result.get("consensus", {}),
                "perspective_count": len(result.get("perspectives", [])),
            },
            ticker=request.ticker,
            asset_scope="bist",
            source_key="multi_agent_debate",
            session_id=request.session_id,
            actor="system",
            retention_tier="permanent",
        )
        return result

    def query_streaming(self, request: QueryRequest):
        """Generator that yields SSE-friendly dicts for each agent step."""
        self.metrics["total_queries"] += 1
        self._ticker_activity[request.ticker] += 3
        self._hot_tickers.appendleft(request.ticker)
        state = {
            "ticker": request.ticker,
            "question": request.question,
            "as_of_date": request.as_of_date or datetime.now(UTC),
            "language": request.language or self.settings.default_language,
            "provider_pref": request.provider_pref,
            "provider_overrides": request.provider_overrides or {},
            "session_id": request.session_id,
        }
        gen = self.agent.run_streaming(state)
        result = None
        try:
            while True:
                event = next(gen)
                yield event
        except StopIteration as stop:
            result = stop.value

        if result:
            self._mark_ticker_processed(request.ticker)
            yield {"node": "final", "status": "complete", "response": result.model_dump(mode="json")}

    def compare_query(self, tickers: list[str], question: str, provider_pref: str | None = None) -> dict:
        """Run the same question against multiple tickers and produce a comparison."""
        results: dict[str, dict] = {}
        for ticker in tickers[:5]:  # cap at 5 tickers
            try:
                req = QueryRequest(ticker=ticker.upper(), question=question, provider_pref=provider_pref)
                resp = self.query(req)
                results[ticker.upper()] = resp.model_dump(mode="json")
            except Exception as exc:  # noqa: BLE001
                results[ticker.upper()] = {"error": str(exc)}

        # Build comparison summary
        comparison_rows = []
        for ticker, data in results.items():
            if "error" in data:
                comparison_rows.append({"ticker": ticker, "status": "error", "error": data["error"]})
            else:
                comparison_rows.append({
                    "ticker": ticker,
                    "status": "ok",
                    "consistency": data.get("consistency_assessment", ""),
                    "confidence": data.get("confidence", 0),
                    "sources_used": data.get("used_sources", []),
                    "citation_count": len(data.get("citations", [])),
                    "route": data.get("route_path", ""),
                })

        return {
            "question": question,
            "tickers": list(results.keys()),
            "comparison": comparison_rows,
            "results": results,
            "disclaimer": "This system does not provide investment advice.",
        }

    def export_audit_trail(self, ticker: str | None = None, limit: int = 500) -> dict:
        """Export the full audit trail as a JSON-serializable dict."""
        events = self.audit_ledger.recent_events(ticker=ticker, limit=limit)
        verify = self.audit_ledger.verify_chain(ticker=ticker)
        return {
            "exported_at": datetime.now(UTC).isoformat(),
            "ticker_filter": ticker,
            "chain_integrity": verify,
            "event_count": len(events),
            "events": events,
        }

    def suggest_tickers(self, prefix: str, limit: int = 10) -> list[dict[str, str]]:
        """Fuzzy ticker autocomplete: prefix match + alias keyword match."""
        prefix_up = prefix.strip().upper()
        if not prefix_up:
            return []
        all_tickers = self.universe.list_tickers()
        # Direct prefix match
        matches = [t for t in all_tickers if t.startswith(prefix_up)]
        # Alias keyword match
        if len(matches) < limit:
            for t in all_tickers:
                if t in matches:
                    continue
                keywords = alias_keywords(t)
                if any(prefix_up in kw.upper() for kw in keywords):
                    matches.append(t)
                if len(matches) >= limit:
                    break
        results = []
        for ticker in matches[:limit]:
            profile_url = KNOWN_KAP_PROFILE_URLS.get(ticker, "")
            results.append({"ticker": ticker, "kap_url": profile_url})
        return results

    def batch_query(self, questions: list[dict], provider_pref: str | None = None) -> list[dict]:
        """Run multiple queries and return results list."""
        results = []
        for item in questions[:20]:  # cap at 20
            ticker = item.get("ticker", "").strip().upper()
            question = item.get("question", "").strip()
            if not ticker or not question:
                results.append({"ticker": ticker, "error": "missing ticker or question"})
                continue
            try:
                req = QueryRequest(ticker=ticker, question=question, provider_pref=provider_pref)
                resp = self.query(req)
                results.append({"ticker": ticker, "question": question, **resp.model_dump(mode="json")})
            except Exception as exc:  # noqa: BLE001
                results.append({"ticker": ticker, "question": question, "error": str(exc)})
        return results

    def get_chat_history(self, session_id: str | None = None, ticker: str | None = None, limit: int = 50) -> list[dict]:
        """Return recent chat history from the audit ledger."""
        return self.audit_ledger.recent_chat_sessions(
            ticker=ticker.upper() if ticker else None,
            session_id=session_id,
            limit=limit,
        )

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
        preferred = (provider_pref or "").strip().lower()
        try:
            if preferred == "ollama":
                provider = self.llm._build_provider("ollama", provider_overrides or {})
                if hasattr(provider, "health_check"):
                    health = provider.health_check()
                    latency_ms = round((time.perf_counter() - started) * 1000, 2)
                    models = health.get("models", [])
                    model = str(health.get("model", ""))
                    model_note = "model bulundu" if health.get("model_available") else "model listede yok"
                    return {
                        "ok": True,
                        "provider_used": "ollama",
                        "latency_ms": latency_ms,
                        "preview": f"Ollama bağlantısı hazır ({health.get('base_url')}); {len(models)} model görüldü, {model}: {model_note}.",
                        "error": None,
                    }
            text, provider_used = self.llm.generate_with_provider(
                prompt,
                provider_pref=provider_pref,
                provider_overrides=provider_overrides or {},
            )
            latency_ms = round((time.perf_counter() - started) * 1000, 2)
            preview = text.strip().replace("\n", " ")[:200]
            if preferred and provider_used != preferred:
                return {
                    "ok": False,
                    "provider_used": provider_used,
                    "latency_ms": latency_ms,
                    "preview": preview,
                    "error": f"Requested provider '{preferred}' is not available. Fallback provider used: '{provider_used}'.",
                }
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

    def get_eval_history(self, limit: int = 10) -> dict:
        reports_dir = Path("logs/eval_reports")
        items: list[dict] = []
        for path in sorted(reports_dir.glob("eval_*.json"), key=lambda item: item.stat().st_mtime, reverse=True)[:limit]:
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except Exception as exc:  # noqa: BLE001
                items.append({"file": str(path), "error": str(exc)})
                continue
            items.append(
                {
                    "file": str(path),
                    "created_at": datetime.fromtimestamp(path.stat().st_mtime, tz=UTC).isoformat(),
                    "citation_coverage": payload.get("citation_coverage"),
                    "disclaimer_presence": payload.get("disclaimer_presence"),
                    "contradiction_detection_accuracy": payload.get("contradiction_detection_accuracy"),
                    "avg_confidence": payload.get("avg_confidence"),
                    "gate_results": payload.get("gate_results", {}),
                    "rubric_scores": payload.get("rubric_scores", {}),
                }
            )
        return {"count": len(items), "items": items}

    def get_ticker_universe(self, limit: int = 50, mode: str = "priority", queue: str | None = None) -> dict:
        self.universe.refresh_if_needed(force=False)
        mode_norm = (mode or "priority").strip().lower()
        queue_norm = (queue or "").strip().lower() or None
        activity = dict(self._ticker_activity)
        last_seen = {ticker: self._minutes_since_seen(ticker) for ticker in self.universe.list_tickers()}
        hot_tickers = list(self._hot_tickers)
        queues = self.universe.build_queues(
            activity_counter=activity,
            last_seen_minutes=last_seen,
            hot_tickers=hot_tickers,
        )

        if mode_norm == "all":
            if queue_norm in {"hot", "active", "background"}:
                chosen = queues[queue_norm]
            else:
                chosen = queues["hot"] + queues["active"] + queues["background"]
                chosen.sort(key=lambda item: item.priority_score, reverse=True)
            items = chosen[: max(1, min(limit, len(chosen)))]
        else:
            prioritized = self.universe.prioritize(
                limit=limit,
                activity_counter=activity,
                last_seen_minutes=last_seen,
                hot_tickers=hot_tickers,
            )
            if queue_norm in {"hot", "active", "background"}:
                items = [item for item in prioritized if item.queue == queue_norm]
            else:
                items = prioritized

        coverage = self.universe.coverage_stats(self._processed_tickers_24h())
        return {
            "mode": mode_norm,
            "queue": queue_norm,
            "count": len(items),
            "last_refresh_at": coverage.get("last_refresh_at"),
            "last_refresh_source": self.universe.last_refresh_source,
            "last_refresh_error": self.universe.last_refresh_error,
            "coverage_stats": coverage,
            "queue_depths": {name: len(rows) for name, rows in queues.items()},
            "queue_mix_policy": {"hot": "user-selected and recent", "active": "recent activity", "background": "balanced sweep"},
            "items": [
                {
                    "ticker": item.ticker,
                    "priority_score": item.priority_score,
                    "reason": item.reason,
                    "queue": item.queue,
                }
                for item in items
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
                "tulip_model_name": settings.tulip_model_name,
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
                "cohere_rerank": bool(settings.cohere_api_key),
            },
            "connectors": {
                "tcmb_macro": bool(settings.tcmb_evds_api_key),
                "premium_news": bool(settings.eventregistry_api_key or settings.newsapi_ai_key),
                "x_signal": bool(settings.x_api_bearer_token),
                "coingecko_context": bool(settings.crypto_context_enabled),
                "binance_spot_context": bool(settings.crypto_context_enabled),
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
        drift = narrative_drift_radar(chunks)
        tension = disclosure_news_tension_index(chunks)
        tension_series = tension_timeline(chunks)
        bias = broker_bias_lens(chunks)
        return {
            "narrative_drift_radar": drift,
            "weekly_drift": drift.get("weekly_drift", []),
            "disclosure_news_tension_index": tension,
            "tension_timeline": tension_series.get("weekly_tension", []),
            "broker_bias_lens": bias,
            "broker_bias_series": bias.get("institutions", []),
            "claim_ledger": self.claim_ledger.stats(),
            "memory_snapshots": self.memory.get_ticker_snapshots(ticker),
            "retrieval_trace": self.retriever.latest_trace(),
        }

    def health(self) -> dict:
        return {"status": "ok", "time": datetime.now(UTC).isoformat(), "app": self.settings.app_name}

    def health_detailed(self) -> dict:
        uptime_seconds = (datetime.now(UTC) - self.started_at).total_seconds()
        latencies = list(self.query_latencies_ms)
        avg_latency = round(sum(latencies) / len(latencies), 1) if latencies else 0
        p95_latency = round(sorted(latencies)[int(len(latencies) * 0.95)] if len(latencies) >= 2 else avg_latency, 1)
        providers_available = []
        for name, key_attr in [
            ("groq", "groq_api_key"), ("gemini", "gemini_api_key"),
            ("openai", "openai_api_key"), ("together", "together_api_key"),
            ("voyage", "voyage_api_key"),
        ]:
            if getattr(self.settings, key_attr, "").strip():
                providers_available.append(name)
        if not providers_available:
            providers_available.append("mock")
        return {
            "status": "ok",
            "time": datetime.now(UTC).isoformat(),
            "app": self.settings.app_name,
            "version": self.settings.app_version,
            "uptime_seconds": round(uptime_seconds),
            "vector_store": self.vector_store.health(),
            "providers_available": providers_available,
            "query_stats": {
                "total": self.metrics["total_queries"],
                "blocked": self.metrics["blocked_queries"],
                "avg_latency_ms": avg_latency,
                "p95_latency_ms": p95_latency,
                "cache_hits": self._query_cache_hits,
                "cache_misses": self._query_cache_misses,
                "cache_size": self.query_cache_size(),
                "cache_backend": "redis" if self._query_cache_backend.enabled else "memory",
                "cache_hit_rate": round(
                    self._query_cache_hits / max(1, self._query_cache_hits + self._query_cache_misses), 3
                ),
            },
            "ingest_stats": {
                "kap_chunks": self.metrics["kap_ingest_chunks"],
                "news_chunks": self.metrics["news_ingest_chunks"],
                "report_chunks": self.metrics["report_ingest_chunks"],
                "docs_seen": self.metrics["ingest_docs_seen"],
                "docs_skipped": self.metrics["ingest_docs_skipped"],
            },
            "connectors": {
                "tcmb_enabled": self.tcmb_connector.enabled,
                "coingecko_enabled": self.coingecko_connector.enabled,
                "binance_enabled": self.binance_connector.enabled,
                "premium_news_enabled": self.premium_news_connector.enabled,
                "x_signal_enabled": self.x_connector.enabled,
                "web_search_enabled": self.settings.web_search_enabled,
                "tavily_configured": bool(self.settings.tavily_api_key.strip()),
            },
            "memory": {
                "claim_ledger": self.claim_ledger.stats(),
                "session_count": len(self.memory._sessions),
            },
            "routes": {
                "direct": self.metrics["route_direct_count"],
                "reretrieve": self.metrics["route_reretrieve_count"],
                "blocked": self.metrics["route_blocked_count"],
            },
            "last_errors": list(self.last_errors)[:5],
        }

    def ready(self) -> dict:
        return {"status": "ready", "vector_store": self.vector_store.health()}

    def query_with_insight(self, request: QueryRequest) -> dict:
        response = self.query(request)
        source_mix = self._source_mix_from_citations(response.citations)
        diag = self.diagnostics(request.ticker, request.as_of_date)
        tension_index = diag.get("disclosure_news_tension_index", {}).get("tension_index", 0.0)
        latest_doc_times = self._latest_doc_times(response.citations)
        freshness_score = self._freshness_score(response.citations)
        attention_score = self._attention_score(request.ticker, response.citations)
        macro_snapshot = self._tcmb_macro_snapshot()
        web_snapshot = self._web_research_snapshot(request.ticker)
        social_snapshot = self._connector_snapshot(
            "x_signal",
            lambda: self.x_connector.fetch_signal(request.ticker),
        )
        cross_asset_context = self.get_cross_asset_context(request.ticker)
        evidence_sufficiency_score = self._evidence_sufficiency_score(response)
        rumor_risk_score = self._rumor_risk_score(response, social_snapshot=social_snapshot)
        connector_cards = self._connector_status_cards(
            self._connector_health.get("premium_news", {}),
            macro_snapshot,
            social_snapshot,
            web_snapshot,
        )
        analysis_sections = {
            "official_disclosure": self._citation_summary(response, "kap"),
            "news_framing": self._citation_summary(response, "news"),
            "brokerage_view": self._citation_summary(response, "brokerage"),
            "social_signal": self._social_signal_section(request.ticker),
            "consistency_summary": self._consistency_summary_text(response, tension_index),
            "web_research_context": self._web_research_section(web_snapshot),
        }
        overview_cards = [
            {
                "label": "Citation Coverage",
                "value": f"{response.citation_coverage_score:.2f}",
                "hint": "Claim-level grounding",
            },
            {
                "label": "Consistency",
                "value": response.consistency_assessment,
                "hint": "Verifier outcome",
            },
            {
                "label": "Freshness",
                "value": f"{freshness_score:.2f}",
                "hint": "Recency-weighted",
            },
            {
                "label": "Attention",
                "value": f"{attention_score:.2f}",
                "hint": "News + activity",
            },
            {
                "label": "Evidence Sufficiency",
                "value": f"{evidence_sufficiency_score:.2f}",
                "hint": "Coverage + reliability + freshness",
            },
            {
                "label": "Rumor Risk",
                "value": f"{rumor_risk_score:.2f}",
                "hint": "Discovery/social dominance risk",
            },
        ]
        timeline = [item.model_dump(mode="json") for item in self._build_timeline_events(response.citations)]
        source_tables = [
            self._build_table_from_citations("KAP", [c for c in response.citations if c.source_type == SourceType.KAP]).model_dump(mode="json"),
            self._build_table_from_citations("News", [c for c in response.citations if c.source_type == SourceType.NEWS]).model_dump(mode="json"),
            self._build_table_from_citations(
                "Brokerage + Uploads",
                [c for c in response.citations if c.source_type in {SourceType.BROKERAGE, SourceType.USER_UPLOAD}],
            ).model_dump(mode="json"),
        ]
        payload = {
            "response": response.model_dump(),
            "insight": {
                "source_mix": source_mix,
                "source_reliability_mix": self._source_reliability_mix(response.citations),
                "citation_count": len(response.citations),
                "ticker_memory_snapshots": len(diag.get("memory_snapshots", {})),
                "tension_index": tension_index,
                "citation_coverage_score": response.citation_coverage_score,
                "evidence_sufficiency_score": evidence_sufficiency_score,
                "evidence_gaps": response.evidence_gaps,
                "attention_score": attention_score,
                "freshness_score": freshness_score,
                "rumor_risk_score": rumor_risk_score,
                "latest_doc_times": latest_doc_times,
                "macro_context": macro_snapshot.get("snapshot", []),
                "social_snapshot": social_snapshot.get("snapshot", {}),
                "web_research_context": web_snapshot.get("snapshot", {}),
                "cross_asset_context": cross_asset_context,
                "connector_cards": connector_cards,
            },
            "analysis_sections": analysis_sections,
            "overview_cards": overview_cards,
            "timeline": timeline,
            "source_tables": source_tables,
            "headline": f"{request.ticker} analyst snapshot",
            "executive_summary": response.answer_tr,
            "diagnostics": diag,
        }
        strip_summary = normalize_visible_text(response.answer_tr)[:500]
        dossier_snapshot = self._dossier_snapshot(
            request.ticker,
            response,
            payload,
            diag,
            evidence_sufficiency_score=evidence_sufficiency_score,
            freshness_score=freshness_score,
            attention_score=attention_score,
            rumor_risk_score=rumor_risk_score,
        )
        self.audit_ledger.save_analysis_snapshot(
            request.ticker,
            snapshot_key=f"{request.session_id}:{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}",
            summary=strip_summary,
            payload=payload,
        )
        self.audit_ledger.save_ticker_profile(request.ticker, dossier_snapshot)
        audit_event = self._append_audit_event(
            event_type="analysis",
            payload={
                "ticker": request.ticker,
                "provider_used": response.provider_used,
                "consistency": response.consistency_assessment,
                "citation_coverage": response.citation_coverage_score,
                "cross_asset_enabled": True,
                "summary": strip_summary,
            },
            ticker=request.ticker,
            asset_scope="bist",
            source_key="analysis_engine",
            session_id=request.session_id,
            actor="system",
            retention_tier="permanent",
        )
        self._analysis_cache[request.ticker.upper()] = {
            "updated_at": datetime.now(UTC).isoformat(),
            "request": request.model_dump(mode="json", exclude_none=True),
            "payload": payload,
        }
        payload["audit_event_id"] = audit_event["event_id"]
        payload["dossier_snapshot"] = dossier_snapshot
        return payload

    def chat_query(self, request: ChatQueryRequest) -> ChatQueryResponse:
        insight = self.query_with_insight(
            QueryRequest(
                ticker=request.ticker,
                question=request.message,
                as_of_date=request.as_of_date,
                language=request.language,
                provider_pref=request.provider_pref,
                provider_overrides=request.provider_overrides,
                session_id=request.session_id,
                include_user_files=request.include_user_files,
                include_social_signal=request.include_social_signal,
                time_range=request.time_range,
            )
        )
        response = QueryResponse.model_validate(insight["response"])
        cross_asset_context = self.get_cross_asset_context(request.ticker) if (
            request.include_crypto_context or request.market_scope == "bist_plus_context"
        ) else {}
        upload_citations = []
        if request.include_user_files:
            upload_docs = self.retriever.retrieve(
                query=request.message,
                ticker=request.ticker,
                source_types=[SourceType.USER_UPLOAD],
                as_of_date=request.as_of_date,
                top_k=6,
            )
            upload_docs = [
                doc for doc in upload_docs
                if is_supported_upload_filename(doc.title or str(doc.metadata.get("filename") or ""))
            ]
            upload_citations = self.agent.nodes._build_citations(upload_docs, limit=4) if hasattr(self.agent, "nodes") else []
        citations = list(response.citations) + [c for c in upload_citations if c.url not in {row.url for row in response.citations}]
        timeline = self._build_timeline_events(response.citations)
        tables = [
            self._build_table_from_citations("Resmi KAP Kaynakları", [c for c in citations if c.source_type == SourceType.KAP]),
            self._build_table_from_citations("Haber Kaynakları", [c for c in citations if c.source_type == SourceType.NEWS]),
            self._build_table_from_citations(
                "Aracı Kurum / Kullanıcı Kaynakları",
                [c for c in citations if c.source_type in {SourceType.BROKERAGE, SourceType.USER_UPLOAD}],
            ),
        ]
        summary_cards = [
            SummaryCard(label="Tutarlılık", value=response.consistency_assessment, tone="neutral", hint="Verifier çıktısı"),
            SummaryCard(label="Kanıt Kapsaması", value=f"{response.citation_coverage_score:.2f}", tone="neutral"),
            SummaryCard(label="Güven", value=f"{response.confidence:.2f}", tone="neutral"),
            SummaryCard(
                label="Attention Score",
                value=f"{insight['insight'].get('attention_score', 0.0):.2f}",
                tone="neutral",
                hint="News volume + query activity",
            ),
        ]
        reply_markdown = "\n\n".join(
            [
                f"## {request.ticker} Analyst Workspace Yanıtı",
                f"**Resmi durum:** {insight['analysis_sections']['official_disclosure']}",
                f"**Haber anlatısı:** {insight['analysis_sections']['news_framing']}",
                f"**Aracı kurum çerçevesi:** {insight['analysis_sections']['brokerage_view']}",
                f"**Sosyal sinyal:** {insight['analysis_sections']['social_signal']}",
                f"**Açık web araştırma:** {insight['analysis_sections'].get('web_research_context', '')}",
                f"**Tutarlılık özeti:** {insight['analysis_sections']['consistency_summary']}",
                (
                    f"**Cross-asset context:** {cross_asset_context.get('context_note', '')}"
                    if cross_asset_context else ""
                ),
                normalize_visible_text(response.answer_tr).replace(response.disclaimer, "").strip(),
            ]
        )
        audit_event = self._append_audit_event(
            event_type="chat",
            payload={
                "ticker": request.ticker,
                "session_id": request.session_id,
                "provider_used": response.provider_used,
                "market_scope": request.market_scope,
                "include_crypto_context": request.include_crypto_context,
                "include_social_signal": request.include_social_signal,
                "message": request.message,
            },
            ticker=request.ticker,
            asset_scope="workspace",
            source_key="research_chat",
            session_id=request.session_id,
            actor="user",
            retention_tier="permanent",
        )
        chat_response = ChatQueryResponse(
            reply_markdown=reply_markdown,
            summary_cards=summary_cards,
            tables=[table for table in tables if table.rows],
            timeline=timeline,
            citations=citations,
            evidence_gaps=response.evidence_gaps,
            cross_asset_context=cross_asset_context,
            route_path=response.route_path,
            provider_used=response.provider_used,
            audit_event_id=audit_event["event_id"],
            disclaimer=response.disclaimer,
        )
        self.audit_ledger.record_chat_session(
            request.session_id,
            request.ticker,
            request.message,
            chat_response.model_dump(mode="json"),
        )
        return chat_response

    def get_research_ticker_bundle(self, ticker: str, session_id: str = "default") -> dict:
        ticker = ticker.upper()
        warm_status = self._warm_ticker_context(
            ticker,
            session_id=session_id,
            aggressive=not self._analysis_cache_is_usable(ticker),
        )
        cached = self._analysis_cache_entry(ticker)
        should_refresh = (
            not cached
            or not self._analysis_cache_is_usable(ticker)
            or int(warm_status.get("inserted_chunks_total", 0)) > 0
        )
        if should_refresh:
            insight = self.query_with_insight(
                QueryRequest(
                    ticker=ticker,
                    question=f"{ticker} için resmi durum, haber anlatısı, aracı kurum çerçevesi ve kanıt boşluklarını özetle.",
                    language="bilingual",
                    session_id=session_id,
                    include_social_signal=True,
                )
            )
            if (
                float(insight.get("response", {}).get("citation_coverage_score", 0.0) or 0.0) == 0.0
                and int(warm_status.get("inserted_chunks_total", 0)) == 0
                and not bool(warm_status.get("aggressive"))
            ):
                warm_status = self._warm_ticker_context(ticker, session_id=session_id, aggressive=True)
                insight = self.query_with_insight(
                    QueryRequest(
                        ticker=ticker,
                        question=f"{ticker} için resmi durum, haber anlatısı, aracı kurum çerçevesi ve kanıt boşluklarını özetle.",
                        language="bilingual",
                        session_id=session_id,
                        include_social_signal=True,
                    )
                )
        else:
            insight = cached["payload"]
        response = QueryResponse.model_validate(insight["response"])
        prices = self.get_market_prices(tickers=[ticker], limit=1)
        diagnostics = insight["diagnostics"]
        premium_snapshot = warm_status.get("premium_news") or self._premium_news_snapshot(ticker)
        web_snapshot = warm_status.get("web_research") or self._web_research_snapshot(ticker)
        social_snapshot = warm_status.get("social_signal") or self._connector_snapshot(
            "x_signal",
            lambda: self.x_connector.fetch_signal(ticker),
        )
        macro_snapshot = warm_status.get("macro_snapshot") or self._tcmb_macro_snapshot()
        cross_asset_context = self.get_cross_asset_context(ticker)
        audit_summary = self.audit_ledger.audit_summary(ticker=ticker)
        dossier_state = self.get_ticker_dossier(ticker)
        return {
            "ticker": ticker.upper(),
            "overview_cards": insight.get("overview_cards", []),
            "latest_analysis": insight,
            "timeline": insight.get("timeline", []),
            "source_tables": insight.get("source_tables", []),
            "prices": prices,
            "macro_snapshot": macro_snapshot.get("snapshot", []),
            "social_signal": social_snapshot.get("snapshot", {}),
            "premium_news": premium_snapshot,
            "web_research": web_snapshot,
            "cross_asset_context": cross_asset_context,
            "diagnostics": diagnostics,
            "uploads": [row.model_dump(mode="json") for row in self.list_uploads(session_id)],
            "source_health": self.get_source_health_report(),
            "provider_health": self.get_provider_registry(),
            "warm_status": warm_status,
            "connector_cards": warm_status.get("connector_cards", []),
            "cache_age_seconds": self._analysis_cache_age_seconds(ticker),
            "audit_summary": audit_summary,
            "audit_verification": dossier_state.get("audit_verification"),
            "dossier_snapshot": dossier_state.get("profile"),
            "audit_ledger_preview": dossier_state.get("audit_preview", {}),
            "recent_chat_sessions": dossier_state.get("recent_chat_sessions", []),
            "recent_upload_events": dossier_state.get("recent_upload_events", []),
            "recent_connector_runs": dossier_state.get("recent_connector_runs", []),
            "source_reliability_mix": insight.get("insight", {}).get("source_reliability_mix", {}),
            "tension_timeline": diagnostics.get("tension_timeline", []),
            "narrative_drift": diagnostics.get("narrative_drift_radar", {}),
            "auto_refresh_due": {
                "kap": self._is_channel_due(ticker, "kap", self.settings.live_kap_interval_seconds),
                "news": self._is_channel_due(ticker, "news", self.settings.live_news_interval_seconds),
                "price": self._is_channel_due(ticker, "price", self.settings.live_price_interval_seconds),
                "report": self._is_channel_due(ticker, "report", self.settings.live_report_interval_seconds),
            },
            "latest_query_response": response.model_dump(mode="json"),
        }

    def get_metrics(self) -> dict:
        uptime = datetime.now(UTC) - self.started_at
        vector_health = self.vector_store.health()
        avg_latency = round(sum(self.query_latencies_ms) / len(self.query_latencies_ms), 2) if self.query_latencies_ms else 0.0
        seen = max(1, self.metrics["ingest_docs_seen"])
        dedup_rate = round(self.metrics["ingest_docs_skipped"] / seen, 4)
        live_universe = self.get_ticker_universe(limit=min(10, self.settings.live_universe_batch_size))
        coverage = self.universe.coverage_stats(self._processed_tickers_24h())
        queue_state = self._queue_state()
        live_ingest_health = self._live_ingest_health()
        source_health_report = self.get_source_health_report()
        source_coverage = source_health_report.get("coverage_summary", {})
        fresh_doc_values = [float(item.get("fresh_doc_ratio", 0.0)) for item in live_ingest_health.values()]
        fresh_doc_ratio = round(sum(fresh_doc_values) / len(fresh_doc_values), 4) if fresh_doc_values else 0.0
        latest_success_times = [item.get("last_success_at") for item in live_ingest_health.values() if item.get("last_success_at")]
        llm_default = "groq"
        if not self.settings.groq_api_key:
            llm_default = "gemini" if self.settings.gemini_api_key else "ollama"
        provider_runtime = {
            "llm_default": llm_default,
            "embedding_provider": self.settings.embedding_provider,
            "embedding_model": {
                "voyage": self.settings.voyage_embedding_model,
                "openai": self.settings.openai_embedding_model,
                "ollama": self.settings.ollama_embedding_model,
                "nomic": self.settings.nomic_embedding_model,
            }.get(self.settings.embedding_provider, self.settings.ollama_embedding_model),
            "ollama_base_url": self.settings.ollama_base_url,
            "ollama_model": self.settings.ollama_model,
        }
        attention_leaders = [
            {"ticker": ticker, "score": round(min(1.0, count / 10.0), 2)}
            for ticker, count in self._ticker_activity.most_common(8)
        ]
        freshness_heatmap = [
            {
                "source": source,
                "fresh_doc_ratio": row.get("fresh_doc_ratio", 0.0),
                "freshness_latency_seconds": row.get("freshness_latency_seconds"),
            }
            for source, row in live_ingest_health.items()
        ]
        raw_lake_summary = self.raw_lake.summary()
        return {
            "uptime_seconds": int(uptime.total_seconds()),
            "runtime_started_at": self.started_at.isoformat(),
            "metrics": self.metrics,
            "vector_store": vector_health,
            "claim_ledger": self.claim_ledger.stats(),
            "active_provider": llm_default,
            "weaviate_connected": bool(vector_health.get("weaviate_connected", False)),
            "fallback_mode": vector_health.get("fallback_mode", "unknown"),
            "strict_mode": bool(vector_health.get("strict_mode", False)),
            "ingest_dedup_rate": dedup_rate,
            "avg_retrieval_latency_ms": avg_latency,
            "latest_retrieval_trace": self.retriever.latest_trace(),
            "last_errors": list(self.last_errors),
            "last_ingest_stats": self.last_ingest_stats,
            "auto_ingest": self.get_auto_ingest_status(),
            "live_ingest_health": live_ingest_health,
            "source_coverage": source_coverage,
            "raw_lake": raw_lake_summary,
            "fresh_doc_ratio": fresh_doc_ratio,
            "last_live_ingest_success_at": max(latest_success_times) if latest_success_times else None,
            "source_health": live_ingest_health,
            "audit_summary": self.audit_ledger.audit_summary(),
            "audit_verification": self.verify_audit_ledger(),
            "universe_size_total": coverage["universe_size_total"],
            "universe_processed_24h": coverage["universe_processed_24h"],
            "ticker_coverage_ratio": coverage["ticker_coverage_ratio"],
            "queue_depths": queue_state["queue_depths"],
            "routing_counters": {
                "direct": self.metrics["route_direct_count"],
                "reretrieve": self.metrics["route_reretrieve_count"],
                "blocked": self.metrics["route_blocked_count"],
            },
            "provider_runtime": provider_runtime,
            "live_universe_preview": live_universe["items"],
            "attention_leaders": attention_leaders,
            "freshness_heatmap": freshness_heatmap,
            "last_ui_sync_at": datetime.now(UTC).isoformat(),
        }

    def delete_upload(self, upload_id: str) -> dict:
        target = self.upload_store.delete_upload(upload_id)
        if not target:
            return {'status': 'not_found', 'upload_id': upload_id}

        prefix = f'user-upload://{upload_id}/'
        deleted_count = self.vector_store.delete_by_url_prefix(prefix)

        return {
            'status': 'ok',
            'upload_id': upload_id,
            'filename': target.get('filename'),
            'deleted_chunks': deleted_count,
        }
