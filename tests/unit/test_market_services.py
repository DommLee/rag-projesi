from datetime import UTC, datetime

from app.market.prices import MarketPriceService, PricePoint
from app.market.universe import BISTUniverseService
from app.schemas import SourceType
from app.service import BISTAgentService


def test_universe_prioritize_with_activity(tmp_path) -> None:
    path = tmp_path / "universe.json"
    path.write_text('["ASELS","THYAO","BIMAS"]', encoding="utf-8")
    service = BISTUniverseService(path)
    ranked = service.prioritize(
        limit=2,
        activity_counter={"THYAO": 10},
        last_seen_minutes={"ASELS": 1, "THYAO": 200, "BIMAS": 3},
    )
    assert len(ranked) == 2
    assert ranked[0].ticker in {"THYAO", "ASELS"}


def test_universe_build_queues_and_coverage(tmp_path) -> None:
    path = tmp_path / "universe.json"
    path.write_text('["ASELS","THYAO","BIMAS","KCHOL"]', encoding="utf-8")
    service = BISTUniverseService(path)

    queues = service.build_queues(
        activity_counter={"THYAO": 4, "BIMAS": 1},
        last_seen_minutes={"ASELS": 2, "THYAO": 45, "BIMAS": 400, "KCHOL": 9999},
        hot_tickers=["ASELS"],
    )
    assert queues["hot"][0].ticker == "ASELS"
    assert any(item.ticker == "THYAO" for item in queues["active"])

    coverage = service.coverage_stats({"ASELS", "THYAO"})
    assert coverage["universe_size_total"] == 4
    assert coverage["universe_processed_24h"] == 2
    assert coverage["ticker_coverage_ratio"] == 0.5


def test_market_price_cache_fallback(monkeypatch) -> None:
    prices = MarketPriceService(ttl_seconds=120)
    cached = PricePoint(
        ticker="ASELS",
        price=100.0,
        change_pct=1.0,
        currency="TRY",
        market_time=datetime.now(UTC),
        provider="yahoo",
        stale=False,
    )
    prices._cache_put(cached)

    monkeypatch.setattr(prices, "_fetch_yahoo", lambda ticker: (_ for _ in ()).throw(RuntimeError("down")))
    monkeypatch.setattr(prices, "_fetch_stooq", lambda ticker: (_ for _ in ()).throw(RuntimeError("down")))

    out = prices.get_price("ASELS", force_refresh=True)
    assert out.provider == "cache"
    assert out.stale is True
    assert out.price == 100.0


def test_connector_snapshot_reuses_disabled_payload(monkeypatch) -> None:
    service = BISTAgentService()
    calls = {"count": 0}

    def fetch():
        calls["count"] += 1
        return {"key": "x_signal", "enabled": False, "status": "disabled", "fetched": 0, "error": "missing"}

    first = service._connector_snapshot("x_signal", fetch)
    second = service._connector_snapshot("x_signal", fetch)

    assert first["status"] == "disabled"
    assert second["status"] == "disabled"
    assert calls["count"] == 1


def test_warm_ticker_context_uses_fast_doc_limits(monkeypatch) -> None:
    service = BISTAgentService()
    captured: list[int] = []

    def fake_ingest(request):
        captured.append(int(request.max_docs or 0))
        return 0

    monkeypatch.setattr(service, "ingest_kap_quick", fake_ingest)
    monkeypatch.setattr(service, "ingest_news", fake_ingest)
    monkeypatch.setattr(
        service.market_prices,
        "get_price",
        lambda ticker, force_refresh=False: PricePoint(
            ticker=ticker,
            price=100.0,
            change_pct=0.0,
            currency="TRY",
            market_time=datetime.now(UTC),
            provider="mock",
            stale=False,
        ),
    )
    monkeypatch.setattr(service, "_premium_news_snapshot", lambda ticker: {"status": "disabled", "enabled": False})
    monkeypatch.setattr(service, "_connector_snapshot", lambda key, fetcher, ttl_seconds=None, reuse_disabled=True: {"status": "disabled", "enabled": False})
    monkeypatch.setattr(service, "_tcmb_macro_snapshot", lambda: {"status": "disabled", "enabled": False, "snapshot": {}})

    service._warm_ticker_context("ASELS", aggressive=False)
    service._warm_ticker_context("ASELS", aggressive=True)

    assert service.settings.warm_ingest_max_docs in captured
    assert service.settings.warm_ingest_max_docs_aggressive in captured


def test_kap_warm_urls_exclude_heavy_disclosure_search() -> None:
    urls = BISTAgentService._kap_warm_urls_for_ticker("ASELS")
    assert urls
    assert all("bildirim-sorgu" not in url for url in urls)


def test_news_warm_urls_use_curated_subset() -> None:
    urls = BISTAgentService._news_warm_urls_for_ticker("ASELS")
    assert "https://www.bloomberght.com/rss" in urls
    assert "https://bigpara.hurriyet.com.tr/rss/" in urls
    assert "https://www.aa.com.tr/tr/rss/default?cat=ekonomi" in urls
    assert "https://www.paraanaliz.com/feed/" not in urls


def test_crypto_context_merges_primary_and_secondary(monkeypatch) -> None:
    service = BISTAgentService()
    service.settings.crypto_context_enabled = True
    monkeypatch.setattr(
        service,
        "_connector_snapshot",
        lambda key, fetcher, ttl_seconds=None, reuse_disabled=True: (
            {
                "key": "coingecko_context",
                "enabled": True,
                "status": "ok",
                "snapshot": [{"symbol": "BTC", "price_usd": 70000, "change_pct_24h": 2.5, "provider": "coingecko"}],
            }
            if key == "coingecko_context"
            else {
                "key": "binance_spot_context",
                "enabled": True,
                "status": "ok",
                "snapshot": [{"symbol": "ETH", "price_usd": 3500, "change_pct_24h": 1.2, "provider": "binance"}],
            }
        ),
    )

    payload = service.get_crypto_context(["BTC", "ETH"])

    assert payload["enabled"] is True
    assert len(payload["items"]) == 2
    assert payload["items"][0]["symbol"] == "BTC"
    assert payload["items"][1]["symbol"] == "ETH"


def test_cross_asset_context_includes_regime_and_cards(monkeypatch) -> None:
    service = BISTAgentService()
    monkeypatch.setattr(
        service,
        "get_crypto_context",
        lambda symbols=None: {
            "enabled": True,
            "items": [
                {"symbol": "BTC", "price_usd": 70000, "change_pct_24h": 3.2, "provider": "coingecko"},
                {"symbol": "ETH", "price_usd": 3500, "change_pct_24h": 2.4, "provider": "coingecko"},
            ],
        },
    )
    monkeypatch.setattr(
        service,
        "_tcmb_macro_snapshot",
        lambda: {"snapshot": [{"label": "usd_try", "value": "38.2"}, {"label": "eur_try", "value": "41.7"}]},
    )
    monkeypatch.setattr(
        service,
        "get_market_prices",
        lambda tickers=None, limit=1, force_refresh=False: {
            "prices": [{"ticker": "ASELS", "price": 102.5, "change_pct": 1.1, "provider": "mock"}]
        },
    )

    payload = service.get_cross_asset_context("ASELS")

    assert payload["market_regime"]["regime"] in {"risk_on", "mixed", "risk_off"}
    assert payload["context_cards"][0]["label"] == "Market Regime"
    assert payload["macro_pairs"][0]["label"] == "USD/TRY"
    assert "breadth_score" in payload["market_regime"]
    assert payload["risk_dashboard"][0]["label"] == "FX Pressure"


def test_evidence_and_rumor_scores_stay_in_bounds() -> None:
    service = BISTAgentService()
    now = datetime.now(UTC)
    response = type(
        "QueryResponseLike",
        (),
        {
            "citation_coverage_score": 0.66,
            "citations": [
                type("CitationLike", (), {"source_type": SourceType.KAP, "date": now})(),
                type("CitationLike", (), {"source_type": SourceType.NEWS, "date": now})(),
            ],
            "consistency_assessment": "inconclusive",
        },
    )()
    social_snapshot = {"snapshot": {"social_confidence": 0.55, "post_count": 24}}

    evidence = service._evidence_sufficiency_score(response)  # type: ignore[arg-type]
    rumor = service._rumor_risk_score(response, social_snapshot=social_snapshot)  # type: ignore[arg-type]

    assert 0.0 <= evidence <= 1.0
    assert 0.0 <= rumor <= 1.0
