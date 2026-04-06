from fastapi.testclient import TestClient

from app.api.main import app


def test_dashboard_available() -> None:
    client = TestClient(app)
    response = client.get("/")
    assert response.status_code == 200
    assert "BIST Agentic RAG Console" in response.text


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
