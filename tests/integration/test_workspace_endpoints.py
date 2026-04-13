from fastapi.testclient import TestClient

from app.api.main import app, service


def test_source_catalog_endpoint(monkeypatch) -> None:
    monkeypatch.setattr(
        service,
        "get_source_catalog",
        lambda: [
            {
                "key": "kap_disclosures",
                "label": "KAP Disclosures",
                "channel": "official",
                "authority_level": "authoritative",
                "asset_scope": "bist",
                "legal_mode": "strict_api_or_low_rate_crawl",
                "freshness_slo_seconds": 300,
                "rate_limit_seconds": 4.0,
                "ticker_resolution_method": "symbol",
                "enabled": True,
                "enabled_by_default": True,
                "kind": "connector",
                "retention_tier": "permanent",
                "notes": "",
            }
        ],
    )
    client = TestClient(app)
    response = client.get("/v1/source-catalog")
    assert response.status_code == 200
    payload = response.json()
    assert payload["count"] == 1
    assert payload["items"][0]["key"] == "kap_disclosures"


def test_workspace_chat_endpoint(monkeypatch) -> None:
    monkeypatch.setattr(
        service,
        "chat_query",
        lambda request: type(
            "FakeChat",
            (),
            {
                "model_dump": lambda self, mode="json": {
                    "reply_markdown": "## ASELS\nResmi durum özetlendi.",
                    "summary_cards": [],
                    "tables": [],
                    "timeline": [],
                    "citations": [],
                    "evidence_gaps": [],
                    "route_path": "direct",
                    "provider_used": "mock",
                    "cross_asset_context": {},
                    "audit_event_id": "evt-1",
                    "disclaimer": "This system does not provide investment advice.",
                }
            },
        )(),
    )
    client = TestClient(app)
    response = client.post("/v1/chat/query", json={"ticker": "ASELS", "message": "özetle"})
    assert response.status_code == 200
    payload = response.json()
    assert "reply_markdown" in payload
    assert payload["provider_used"] == "mock"


def test_workspace_research_bundle_endpoint(monkeypatch) -> None:
    monkeypatch.setattr(
        service,
        "get_research_ticker_bundle",
        lambda ticker, session_id="default": {
            "ticker": ticker,
            "overview_cards": [],
            "latest_analysis": {"response": {"answer_tr": "ok"}},
            "timeline": [],
            "source_tables": [],
            "prices": {"prices": []},
            "diagnostics": {},
            "uploads": [],
            "source_health": {"count": 0, "items": []},
            "provider_health": {"available": {}},
        },
    )
    client = TestClient(app)
    response = client.get("/v1/research/ticker/ASELS")
    assert response.status_code == 200
    assert response.json()["ticker"] == "ASELS"


def test_source_health_endpoint_returns_extended_fields(monkeypatch) -> None:
    monkeypatch.setattr(
        service,
        "get_source_health_report",
        lambda: {
            "count": 1,
            "items": [
                {
                    "key": "aa_rss",
                    "label": "AA Ekonomi RSS",
                    "channel": "media",
                    "authority_level": "tier1_media",
                    "legal_mode": "rss",
                    "freshness_slo_seconds": 60,
                    "rate_limit_seconds": 4.0,
                    "ticker_resolution_method": "alias_and_entity_resolution",
                    "enabled": True,
                    "asset_scope": "bist",
                    "enabled_by_default": True,
                    "retention_tier": "permanent",
                    "notes": "",
                    "fetched": 8,
                    "inserted": 5,
                    "dedup_skipped": 1,
                    "accepted_count": 5,
                    "rejected_entity": 2,
                    "blocked": 0,
                    "retries": 1,
                    "last_success_at": "2026-04-07T10:10:00+00:00",
                    "freshness_latency_seconds": 45,
                    "source_counts": {"AA": 5},
                    "blocked_reason_counts": {},
                    "rejected_samples": [{"title": "Makro veri", "score": 0.12, "reason": "low_confidence_macro_context"}],
                    "disabled_reason": "",
                    "success_rate": 0.625,
                    "source_health_matrix_row": {"fetched": 8, "accepted": 5, "rejected": 2, "blocked": 0},
                    "last_error_at": "2026-04-07T10:10:00+00:00",
                    "error_rate": 0.2,
                }
            ],
        },
    )
    client = TestClient(app)
    response = client.get("/v1/source-health")
    assert response.status_code == 200
    payload = response.json()
    assert payload["count"] == 1
    assert payload["items"][0]["accepted_count"] == 5
    assert payload["items"][0]["rejected_samples"][0]["reason"] == "low_confidence_macro_context"


def test_workspace_upload_endpoint_accepts_multipart(monkeypatch) -> None:
    captured = {}

    def fake_upload(request):
        captured["session_id"] = request.session_id
        captured["ticker"] = request.ticker
        captured["filename"] = request.filename
        captured["content_type"] = request.content_type
        return type(
            "FakeUpload",
            (),
            {
                "model_dump": lambda self, mode="json": {
                    "upload_id": "u1",
                    "session_id": request.session_id,
                    "detected_ticker": request.ticker,
                    "parsed_pages": 1,
                    "inserted_chunks": 2,
                    "warnings": [],
                    "audit_event_id": "evt-upload",
                    "retained_path": "data/uploads/u1.txt",
                    "retention_tier": "permanent",
                }
            },
        )()

    monkeypatch.setattr(service, "upload_document", fake_upload)
    client = TestClient(app)
    response = client.post(
        "/v1/uploads",
        files={"file": ("sample.txt", b"ASELS sample upload", "text/plain")},
        data={"session_id": "chat-a", "ticker": "ASELS"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["upload_id"] == "u1"
    assert captured["session_id"] == "chat-a"
    assert captured["ticker"] == "ASELS"
    assert captured["filename"] == "sample.txt"


def test_cross_asset_context_endpoint(monkeypatch) -> None:
    monkeypatch.setattr(
        service,
        "get_cross_asset_context",
        lambda ticker: {
            "ticker": ticker,
            "asset_scope": "bist_plus_context",
            "crypto_context": {"items": [{"symbol": "BTC", "price_usd": 70000}]},
            "macro_snapshot": [{"label": "usd_try", "value": "32.1"}],
            "market_regime": {"regime": "mixed", "fx_pressure": 0.64},
            "context_cards": [{"label": "Market Regime", "value": "mixed"}],
            "context_note": "context only",
        },
    )
    client = TestClient(app)
    response = client.get("/v1/cross-asset/context?ticker=ASELS")
    assert response.status_code == 200
    assert response.json()["crypto_context"]["items"][0]["symbol"] == "BTC"
    assert response.json()["market_regime"]["regime"] == "mixed"


def test_audit_verify_endpoint(monkeypatch) -> None:
    monkeypatch.setattr(service, "verify_audit_ledger", lambda ticker=None: {"ok": True, "count": 4, "broken_at": None})
    client = TestClient(app)
    response = client.get("/v1/audit/verify?ticker=ASELS")
    assert response.status_code == 200
    assert response.json()["ok"] is True


def test_ticker_dossier_endpoint(monkeypatch) -> None:
    monkeypatch.setattr(
        service,
        "get_ticker_dossier",
        lambda ticker: {
            "ticker": ticker,
            "profile": {"consistency": "aligned", "evidence_sufficiency_score": 0.78},
            "audit_summary": {"chain_ok": True, "repair_count": 1},
            "audit_verification": {"ok": True, "event_type_counts": {"analysis": 2}},
            "audit_preview": {"items": [{"event_type": "analysis"}], "repairs": [{"reason": "legacy_chain_migration"}]},
            "cross_asset_context": {"market_regime": {"regime": "risk_on"}},
            "source_reliability_mix": {"kap": 1.0, "news": 0.7},
        },
    )
    client = TestClient(app)
    response = client.get("/v1/ticker/dossier/ASELS")
    assert response.status_code == 200
    assert response.json()["profile"]["consistency"] == "aligned"
    assert response.json()["audit_preview"]["repairs"][0]["reason"] == "legacy_chain_migration"
    assert response.json()["cross_asset_context"]["market_regime"]["regime"] == "risk_on"
    assert response.json()["audit_verification"]["event_type_counts"]["analysis"] == 2
