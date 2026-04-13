"""Unit tests for the public KAP REST API client.

These tests stub the underlying HTTP layer so they never reach the
network. The goal is to lock in: ticker -> company_id resolution, the
disclosure list -> chunk conversion, and the metadata schema we attach
to every chunk.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from app.ingestion.kap_api import KAPAPIClient, KAPCompanyRef
from app.schemas import SourceType


class _StubResponse:
    def __init__(self, payload, status_code: int = 200, text: str = "") -> None:
        self._payload = payload
        self.status_code = status_code
        self.content = text.encode("utf-8") if text else b""
        self.text = text

    def json(self):
        return self._payload


def test_lookup_company_picks_exact_ticker_match(monkeypatch) -> None:
    client = KAPAPIClient()

    def fake_request(method, url, *, json_body=None, endpoint_label=""):
        assert method == "POST"
        assert "search/combined" in url
        assert json_body == {"keyword": "ASELS"}
        return _StubResponse(
            [
                {
                    "category": "companyOrFunds",
                    "results": [
                        {
                            "cmpOrFundCode": "ASELSY",
                            "memberOrFundOid": "wrong-oid",
                            "searchValue": "Aselsan Yatirim",
                            "searchType": "C",
                        },
                        {
                            "cmpOrFundCode": "ASELS",
                            "memberOrFundOid": "good-oid-12345",
                            "searchValue": "Aselsan Elektronik Sanayi",
                            "searchType": "C",
                        },
                    ],
                }
            ]
        )

    monkeypatch.setattr(client, "_request", fake_request)
    company = client.lookup_company("asels")
    assert company is not None
    assert company.ticker == "ASELS"
    assert company.company_id == "good-oid-12345"
    assert "Aselsan" in company.name

    # Cached on second call — no extra HTTP needed.
    monkeypatch.setattr(
        client,
        "_request",
        lambda *args, **kwargs: pytest.fail("cache miss should not happen"),
    )
    again = client.lookup_company("ASELS")
    assert again is company


def test_collect_disclosures_builds_kap_chunks_with_metadata(monkeypatch) -> None:
    client = KAPAPIClient()
    company = KAPCompanyRef(ticker="THYAO", company_id="thyao-oid", name="Türk Hava Yolları")

    monkeypatch.setattr(client, "lookup_company", lambda ticker: company)
    monkeypatch.setattr(
        client,
        "fetch_disclosure_html",
        lambda idx: f"<html><body><article>{idx} body content for THYAO</article></body></html>",
    )

    fake_rows = [
        {
            "disclosureIndex": 999111,
            "title": "THYAO ozel durum aciklamasi",
            "summary": "operasyonel guncelleme",
            "publishDate": "2026-01-15T10:30:00Z",
            "companyName": "Turk Hava Yollari A.O.",
        }
    ]

    def fake_list(self, comp, *, date_from, date_to, disclosure_class, subject_oid=None):
        if disclosure_class == "ODA":
            return fake_rows
        return []

    monkeypatch.setattr(KAPAPIClient, "list_disclosures_by_criteria", fake_list)
    chunks = client.collect_disclosures(
        "THYAO",
        date_from=datetime(2025, 12, 1, tzinfo=UTC),
        date_to=datetime(2026, 2, 1, tzinfo=UTC),
        disclosure_classes=("ODA", "FR"),
    )
    assert chunks, "expected at least one chunk from KAP API path"
    chunk = chunks[0]
    assert chunk.ticker == "THYAO"
    assert chunk.source_type == SourceType.KAP
    assert chunk.institution.startswith("Turk Hava Yollari") or chunk.institution.startswith("Türk")
    assert chunk.notification_type in {"Material Event", "Financial Report", "Board Decision"}
    assert chunk.metadata.get("kap_disclosure_index") == "999111"
    assert chunk.metadata.get("kap_disclosure_class") == "ODA"
    assert chunk.metadata.get("source_channel") == "kap_api"
    # Mandatory metadata schema
    for field in ("ticker", "source_type", "publication_date", "institution"):
        assert chunk.metadata.get(field), f"missing mandatory metadata field: {field}"


def test_collect_disclosures_returns_empty_when_company_unknown(monkeypatch) -> None:
    client = KAPAPIClient()
    monkeypatch.setattr(client, "lookup_company", lambda ticker: None)
    chunks = client.collect_disclosures("ZZZZZ")
    assert chunks == []
    assert client.last_telemetry["mode"] == "rest_api_no_company"
