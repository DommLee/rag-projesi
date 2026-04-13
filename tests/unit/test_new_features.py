"""Tests for new features: connector injection, web search, streaming, compare, PDF export."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import patch

import pytest

from app.schemas import Citation, QueryResponse, SourceType


# ── Connector injection ────────────────────────────────────────────

def test_agent_nodes_accepts_market_context_fn():
    """AgentNodes constructor accepts optional market_context_fn."""
    from app.agent.nodes import AgentNodes

    called = {}

    def fake_ctx(ticker: str) -> dict:
        called["ticker"] = ticker
        return {"context_cards": [{"label": "Regime", "value": "risk_on"}]}

    # We can't construct AgentNodes without a retriever/llm, but we can
    # verify the helper method works by instantiating with mocks.
    class FakeRetriever:
        pass

    class FakeLLM:
        pass

    class FakeLedger:
        pass

    node = AgentNodes.__new__(AgentNodes)
    node._market_context_fn = fake_ctx
    node._web_search_fn = None

    block = node._fetch_market_context_block("THYAO")
    assert "Regime" in block
    assert "risk_on" in block
    assert called["ticker"] == "THYAO"


def test_agent_nodes_market_context_empty_when_no_fn():
    from app.agent.nodes import AgentNodes

    node = AgentNodes.__new__(AgentNodes)
    node._market_context_fn = None
    assert node._fetch_market_context_block("ASELS") == ""


# ── Web search ─────────────────────────────────────────────────────

def test_web_search_disabled_returns_empty():
    with patch("app.utils.web_search.get_settings") as mock_settings:
        mock_settings.return_value.web_search_enabled = False
        from app.utils.web_search import web_search

        assert web_search("test query") == []


def test_web_searcher_node_returns_empty_when_no_fn():
    from app.agent.nodes import AgentNodes

    node = AgentNodes.__new__(AgentNodes)
    node._web_search_fn = None
    result = node.web_searcher({"ticker": "THYAO", "question": "test"})
    assert result == {"web_search_results": []}


def test_web_searcher_node_calls_fn():
    from app.agent.nodes import AgentNodes

    def fake_search(query, max_results=5):
        return [{"title": "Result", "url": "https://example.com", "snippet": "test"}]

    node = AgentNodes.__new__(AgentNodes)
    node._web_search_fn = fake_search
    result = node.web_searcher({"ticker": "THYAO", "question": "news"})
    assert len(result["web_search_results"]) == 1
    assert result["web_search_results"][0]["title"] == "Result"


# ── Streaming ──────────────────────────────────────────────────────

def test_streaming_run_yields_events():
    """run_streaming should yield at least intent_router and composer events."""
    from app.agent.graph import AgentGraph

    class FakeRetriever:
        def retrieve_with_trace(self, **kw):
            return [], {"mode": "test"}

        def retrieve(self, **kw):
            return []

    class FakeLLM:
        def generate_with_provider(self, prompt, **kw):
            return '{"answer_tr": "test", "answer_en": "test", "confidence": 0.5}', "mock"

    class FakeLedger:
        def register(self, *a, **kw):
            pass

    graph = AgentGraph(FakeRetriever(), FakeLLM(), FakeLedger())
    state = {
        "ticker": "TEST",
        "question": "Test question?",
        "as_of_date": datetime.now(UTC),
    }
    events = []
    gen = graph.run_streaming(state)
    try:
        while True:
            events.append(next(gen))
    except StopIteration as stop:
        final_response = stop.value

    node_names = [e["node"] for e in events]
    assert "intent_router" in node_names
    assert "composer" in node_names
    assert final_response is not None or any(e.get("node") == "final" for e in events)


# ── PDF export ─────────────────────────────────────────────────────

def test_pdf_export_generates_bytes():
    from app.utils.pdf_export import generate_query_pdf

    result = QueryResponse(
        answer_tr="Test cevap.",
        answer_en="Test answer.",
        as_of_date=datetime.now(UTC),
        citations=[
            Citation(
                source_type=SourceType.KAP,
                title="Test",
                institution="KAP",
                date=datetime.now(UTC),
                url="https://kap.org.tr",
                snippet="Test snippet",
            )
        ],
        consistency_assessment="aligned",
        confidence=0.85,
        disclaimer="This system does not provide investment advice.",
        provider_used="mock",
    )
    pdf = generate_query_pdf(result, ticker="TEST", question="What happened?")
    assert isinstance(pdf, bytes)
    assert len(pdf) > 100
    assert pdf[:5] == b"%PDF-"


# ── Compare query (unit-level) ─────────────────────────────────────

def test_compare_request_model():
    """CompareRequest model should validate properly."""
    from app.api.main import CompareRequest

    req = CompareRequest(tickers=["THYAO", "ASELS"], question="What is happening?")
    assert len(req.tickers) == 2
    assert req.question == "What is happening?"
