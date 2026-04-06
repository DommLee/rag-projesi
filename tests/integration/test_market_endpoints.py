from fastapi.testclient import TestClient

from app.api.main import _sse, app, service


def test_market_prices_endpoint(monkeypatch) -> None:
    def fake_prices(tickers=None, limit=12, force_refresh=False):  # noqa: ANN001
        _ = (tickers, limit, force_refresh)
        return {
            "as_of": "2026-04-06T12:00:00+00:00",
            "count": 1,
            "providers_used": ["cache"],
            "prices": [
                {
                    "ticker": "ASELS",
                    "price": 101.25,
                    "change_pct": 1.3,
                    "currency": "TRY",
                    "market_time": "2026-04-06T12:00:00+00:00",
                    "provider": "cache",
                    "stale": True,
                    "note": "",
                }
            ],
        }

    monkeypatch.setattr(service, "get_market_prices", fake_prices)
    client = TestClient(app)
    response = client.get("/v1/market/prices?ticker=ASELS")
    assert response.status_code == 200
    payload = response.json()
    assert payload["count"] == 1
    assert payload["prices"][0]["ticker"] == "ASELS"


def test_market_universe_endpoint(monkeypatch) -> None:
    monkeypatch.setattr(
        service,
        "get_ticker_universe",
        lambda limit=50: {"count": 2, "items": [{"ticker": "ASELS", "priority_score": 9.1, "reason": "test"}]},
    )
    client = TestClient(app)
    response = client.get("/v1/market/universe?limit=2")
    assert response.status_code == 200
    payload = response.json()
    assert payload["count"] == 2
    assert payload["items"][0]["ticker"] == "ASELS"


def test_sse_helper_format() -> None:
    frame = _sse("metrics", {"ok": True})
    assert frame.startswith("event: metrics")
    assert "data:" in frame
