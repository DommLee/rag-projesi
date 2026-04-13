"""Tests for wave 3 features: query cache, analytics, rewriter, alerts."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest


# ── Query cache ────────────────────────────────────────────────────

def test_query_cache_key_deterministic():
    from app.service import BISTAgentService
    from app.schemas import QueryRequest

    req1 = QueryRequest(ticker="THYAO", question="Test?", provider_pref="mock")
    req2 = QueryRequest(ticker="THYAO", question="Test?", provider_pref="mock")
    key1 = BISTAgentService._query_cache_key(req1)
    key2 = BISTAgentService._query_cache_key(req2)
    assert key1 == key2


def test_query_cache_different_for_different_questions():
    from app.service import BISTAgentService
    from app.schemas import QueryRequest

    req1 = QueryRequest(ticker="THYAO", question="Q1?")
    req2 = QueryRequest(ticker="THYAO", question="Q2?")
    assert BISTAgentService._query_cache_key(req1) != BISTAgentService._query_cache_key(req2)


# ── Query rewriter ─────────────────────────────────────────────────

def test_rewriter_fixes_typos():
    from app.utils.query_rewriter import rewrite_query

    result = rewrite_query("borsa istanbul hise analizi")
    assert "hisse" in result


def test_rewriter_expands_abbreviations():
    from app.utils.query_rewriter import rewrite_query

    # SPK is in the expansion map; well-known terms like KAP/TCMB are
    # intentionally NOT expanded to avoid changing question classification.
    result = rewrite_query("spk duzenlemesi")
    assert "Sermaye Piyasasi" in result


def test_rewriter_preserves_well_known_terms():
    from app.utils.query_rewriter import rewrite_query

    original = "ASELS son 6 ayda hangi KAP bildirimleri?"
    result = rewrite_query(original)
    assert "ASELS" in result
    assert "KAP" in result  # preserved, not expanded


def test_rewriter_handles_empty():
    from app.utils.query_rewriter import rewrite_query

    assert rewrite_query("") == ""
    assert rewrite_query("  ") == ""


# ── Alert system ───────────────────────────────────────────────────

def test_alert_manager_emit_and_list():
    from app.alerts import AlertManager, AlertSeverity, AlertType

    mgr = AlertManager()
    alert = mgr.emit(AlertType.CONTRADICTION_DETECTED, "THYAO", "Test contradiction", AlertSeverity.WARNING)
    assert alert is not None
    items = mgr.list_alerts()
    assert len(items) == 1
    assert items[0]["ticker"] == "THYAO"
    assert items[0]["severity"] == "warning"


def test_alert_manager_acknowledge():
    from app.alerts import AlertManager, AlertSeverity, AlertType

    mgr = AlertManager()
    alert = mgr.emit(AlertType.HIGH_TENSION, "ASELS", "High tension", AlertSeverity.CRITICAL)
    assert not alert.acknowledged
    mgr.acknowledge(alert.alert_id)
    items = mgr.list_alerts()
    assert items[0]["acknowledged"] is True


def test_alert_manager_filter_unacknowledged():
    from app.alerts import AlertManager, AlertSeverity, AlertType

    mgr = AlertManager()
    a1 = mgr.emit(AlertType.HIGH_TENSION, "X", "msg1", AlertSeverity.CRITICAL)
    a2 = mgr.emit(AlertType.INGEST_FAILURE, "Y", "msg2", AlertSeverity.CRITICAL)
    mgr.acknowledge(a1.alert_id)
    unacked = mgr.list_alerts(unacknowledged_only=True)
    assert len(unacked) == 1
    assert unacked[0]["alert_id"] == a2.alert_id


def test_alert_manager_stats():
    from app.alerts import AlertManager, AlertSeverity, AlertType

    mgr = AlertManager()
    mgr.emit(AlertType.HIGH_TENSION, "X", "msg1", AlertSeverity.CRITICAL)
    mgr.emit(AlertType.CONTRADICTION_DETECTED, "Y", "msg2", AlertSeverity.WARNING)
    stats = mgr.stats()
    assert stats["total"] == 2
    assert stats["unacknowledged"] == 2
    assert stats["by_severity"]["critical"] == 1
    assert stats["by_severity"]["warning"] == 1


def test_alert_disabled_rule():
    from app.alerts import AlertManager, AlertSeverity, AlertType

    mgr = AlertManager()
    mgr.update_rule("contradiction", enabled=False)
    alert = mgr.emit(AlertType.CONTRADICTION_DETECTED, "X", "should be suppressed")
    assert alert is None
    assert mgr.stats()["total"] == 0


# ── Web search util ─���──────────────────────────────────────────────

def test_web_search_module_importable():
    from app.utils.web_search import web_search
    assert callable(web_search)


# ── Batch query model ──────────────────────────────────────────────

def test_batch_query_request_model():
    from app.api.main import BatchQueryRequest

    req = BatchQueryRequest(questions=[{"ticker": "THYAO", "question": "test"}])
    assert len(req.questions) == 1
