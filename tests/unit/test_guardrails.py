from app.guardrails import append_disclaimer, has_disclaimer, post_answer_policy, pre_answer_policy


def test_investment_advice_prompt_blocked() -> None:
    blocked = pre_answer_policy("ASELS için al sinyali var mı?")
    assert blocked.allowed is False
    blocked_en = pre_answer_policy("Should I buy this stock?")
    assert blocked_en.allowed is False


def test_disclaimer_appended() -> None:
    text = append_disclaimer("Sample answer")
    assert has_disclaimer(text)


def test_post_answer_policy_flags_missing_citations() -> None:
    ok, gaps, score = post_answer_policy("Bu bir cevap. Ikinci cümle.", citations_count=0)
    assert ok is False
    assert "No citations found for generated answer." in gaps
    assert score == 0.0

