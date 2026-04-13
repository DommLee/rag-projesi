from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from app.config import get_settings
from app.guardrails_claims import claim_level_coverage_score
from app.utils.text import normalize_visible_text

INVESTMENT_ADVICE_PATTERNS = [
    r"\b(al|sat|tut)\b",
    r"\bbuy\b",
    r"\bsell\b",
    r"hedef fiyat",
    r"price target",
    r"kac olur",
    r"yukselir mi",
    r"duser mi",
    r"return prediction",
    r"getiri tahmini",
    r"fiyat tahmini",
]


@dataclass
class PolicyDecision:
    allowed: bool
    reason: str
    refusal_tr: str = ""
    refusal_en: str = ""


def _normalize_query(text: str) -> str:
    lowered = normalize_visible_text(text).lower()
    normalized = unicodedata.normalize("NFKD", lowered)
    return "".join(ch for ch in normalized if not unicodedata.combining(ch))


def pre_answer_policy(question: str) -> PolicyDecision:
    text = _normalize_query(question)
    blocked = any(re.search(pattern, text) for pattern in INVESTMENT_ADVICE_PATTERNS)
    if blocked:
        return PolicyDecision(
            allowed=False,
            reason="investment_advice_blocked",
            refusal_tr=(
                "Bu sistem yatirim tavsiyesi, al/sat sinyali veya fiyat/getiri tahmini uretmez. "
                "Yalnizca kanita dayali piyasa anlatisi analizi saglar."
            ),
            refusal_en=(
                "This system does not provide investment advice, buy/sell signals, "
                "or price/return predictions. It only provides evidence-based market narrative analysis."
            ),
        )
    return PolicyDecision(allowed=True, reason="allowed")


def append_disclaimer(text: str) -> str:
    disclaimer = get_settings().disclaimer
    cleaned = normalize_visible_text(text)
    if disclaimer in cleaned:
        return cleaned
    return f"{cleaned.strip()}\n\n{disclaimer}"


def has_disclaimer(text: str) -> bool:
    return get_settings().disclaimer in normalize_visible_text(text)


def citation_coverage_score(answer_text: str, citations: list[object]) -> float:
    score, _ = claim_level_coverage_score(normalize_visible_text(answer_text), citations)
    return score


def post_answer_policy(answer_text: str, citations: list[object]) -> tuple[bool, list[str], float]:
    gaps: list[str] = []
    normalized_answer = normalize_visible_text(answer_text)
    coverage, claim_gaps = claim_level_coverage_score(normalized_answer, citations)
    gaps.extend(normalize_visible_text(item) for item in claim_gaps if item)

    if coverage < 0.5:
        gaps.append("Low claim-level citation coverage.")
    if not has_disclaimer(normalized_answer):
        gaps.append("Missing mandatory disclaimer.")
    return len(gaps) == 0, list(dict.fromkeys(gaps)), coverage
