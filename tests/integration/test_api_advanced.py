from fastapi.testclient import TestClient

from app.api.main import app, service


def test_dashboard_available() -> None:
    client = TestClient(app)
    response = client.get("/")
    assert response.status_code == 200
    assert "BIST Agentic RAG API" in response.text


def test_metrics_endpoint() -> None:
    client = TestClient(app)
    response = client.get("/v1/metrics")
    assert response.status_code == 200
    payload = response.json()
    assert "metrics" in payload
    assert "uptime_seconds" in payload
    assert "routing_counters" in payload


def test_provider_registry_endpoint() -> None:
    client = TestClient(app)
    response = client.get("/v1/providers")
    assert response.status_code == 200
    payload = response.json()
    assert "defaults" in payload
    assert "available" in payload


def test_latest_eval_endpoint_exists() -> None:
    client = TestClient(app)
    response = client.get("/v1/eval/report/latest")
    assert response.status_code == 200
    payload = response.json()
    assert "status" in payload


def test_create_ingest_job() -> None:
    client = TestClient(app)
    response = client.post(
        "/v1/jobs/ingest/news",
        json={
            "ticker": "ASELS",
            "institution": "AA",
            "source_urls": ["https://www.aa.com.tr/tr/rss/default?cat=ekonomi"],
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert "job_id" in payload
    assert payload["job_type"] == "ingest_news"


def test_query_insight_endpoint(monkeypatch) -> None:
    monkeypatch.setattr(
        service,
        "query_with_insight",
        lambda request: {
            "response": {
                "answer_tr": "ornek",
                "answer_en": "sample",
                "as_of_date": "2026-04-07T00:00:00+00:00",
                "citations": [],
                "consistency_assessment": "inconclusive",
                "confidence": 0.5,
                "disclaimer": "This system does not provide investment advice.",
                "blocked": False,
                "citation_coverage_score": 0.0,
                "evidence_gaps": [],
                "used_sources": [],
                "provider_used": "mock",
                "route_path": "direct",
            },
            "analysis_sections": {
                "official_disclosure": "kap",
                "news_framing": "news",
                "brokerage_view": "broker",
                "consistency_summary": "summary",
            },
            "insight": {"citation_count": 0},
            "diagnostics": {},
        },
    )
    client = TestClient(app)
    response = client.post(
        "/v1/query/insight",
        json={"ticker": "ASELS", "question": "latest picture", "language": "bilingual"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["analysis_sections"]["official_disclosure"] == "kap"
