"""Guardrails unit tests with claim-level coverage."""

from datetime import UTC, datetime

from app.guardrails import append_disclaimer, has_disclaimer, pre_answer_policy
from app.guardrails_claims import claim_level_coverage_score
from app.schemas import Citation, SourceType


def _make_citation(snippet: str) -> Citation:
    return Citation(
        source_type=SourceType.KAP,
        title="Test",
        institution="KAP",
        date=datetime.now(UTC),
        url="https://test.local/1",
        snippet=snippet,
    )


def test_investment_advice_prompt_blocked() -> None:
    blocked = pre_answer_policy("ASELS icin al sinyali var mi?")
    assert blocked.allowed is False
    blocked_en = pre_answer_policy("Should I buy this stock?")
    assert blocked_en.allowed is False


def test_price_target_blocked() -> None:
    blocked = pre_answer_policy("THYAO hedef fiyat ne olmali?")
    assert blocked.allowed is False


def test_return_prediction_blocked() -> None:
    blocked = pre_answer_policy("Bu hisse yukselir mi?")
    assert blocked.allowed is False
    blocked2 = pre_answer_policy("Getiri tahmini nedir?")
    assert blocked2.allowed is False


def test_legitimate_query_allowed() -> None:
    allowed = pre_answer_policy("ASELS son KAP bildirimleri nelerdir?")
    assert allowed.allowed is True


def test_disclaimer_appended() -> None:
    text = append_disclaimer("Sample answer")
    assert has_disclaimer(text)


def test_disclaimer_not_duplicated() -> None:
    text = append_disclaimer("Sample answer")
    text2 = append_disclaimer(text)
    assert text2.count("investment advice") == 1


def test_claim_level_coverage_with_citations() -> None:
    answer = "ASELS guclu artis gosterdi. KAP bildirimi olumlu."
    citations = [
        _make_citation("ASELS guclu artis iyilesme performansi"),
        _make_citation("KAP bildirimi olumlu sonuclar"),
    ]
    score, gaps = claim_level_coverage_score(answer, citations)
    assert 0.0 <= score <= 1.0
    assert isinstance(gaps, list)


def test_claim_level_coverage_no_citations() -> None:
    answer = "ASELS guclu artis gosterdi."
    score, gaps = claim_level_coverage_score(answer, [])
    assert score == 0.0
    assert "No citations found for generated answer." in gaps


def test_guardrail_patterns_turkish_chars() -> None:
    assert pre_answer_policy("al sinyali").allowed is False
    assert pre_answer_policy("sat sinyali").allowed is False
    assert pre_answer_policy("hedef fiyat").allowed is False
    assert pre_answer_policy("fiyat tahmini").allowed is False

