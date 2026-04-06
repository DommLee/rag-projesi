from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from app.config import get_settings
from app.guardrails_claims import claim_level_coverage_score


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
    lowered = text.lower()
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
                "Bu sistem yatırım tavsiyesi, al/sat sinyali veya fiyat/getiri tahmini üretmez. "
                "Yalnızca kanıta dayalı piyasa anlatısı analizi sağlar."
            ),
            refusal_en=(
                "This system does not provide investment advice, buy/sell signals, "
                "or price/return predictions. It only provides evidence-based market narrative analysis."
            ),
        )
    return PolicyDecision(allowed=True, reason="allowed")


def append_disclaimer(text: str) -> str:
    disclaimer = get_settings().disclaimer
    if disclaimer in text:
        return text
    return f"{text.strip()}\n\n{disclaimer}"


def has_disclaimer(text: str) -> bool:
    return get_settings().disclaimer in text


def citation_coverage_score(answer_text: str, citations: list[object]) -> float:
    score, _ = claim_level_coverage_score(answer_text, citations)
    return score


def post_answer_policy(answer_text: str, citations: list[object]) -> tuple[bool, list[str], float]:
    gaps: list[str] = []
    coverage, claim_gaps = claim_level_coverage_score(answer_text, citations)
    gaps.extend(claim_gaps)

    if coverage < 0.5:
        gaps.append("Low claim-level citation coverage.")
    if not has_disclaimer(answer_text):
        gaps.append("Missing mandatory disclaimer.")
    return len(gaps) == 0, list(dict.fromkeys(gaps)), coverage
