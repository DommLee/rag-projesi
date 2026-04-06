from datetime import UTC, datetime

from app.market.prices import MarketPriceService, PricePoint
from app.market.universe import BISTUniverseService


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

