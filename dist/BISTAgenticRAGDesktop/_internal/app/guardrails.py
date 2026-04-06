from __future__ import annotations

import re
from dataclasses import dataclass
import unicodedata

from app.config import get_settings
from app.guardrails_claims import claim_coverage_score, decompose_claims, ground_claims


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


def _normalize_query(text: str) -> str:
    lowered = (
        text.lower()
        .replace("ı", "i")
        .replace("ş", "s")
        .replace("ğ", "g")
        .replace("ç", "c")
        .replace("ö", "o")
        .replace("ü", "u")
    )
    normalized = unicodedata.normalize("NFKD", lowered)
    ascii_safe = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    return ascii_safe


def append_disclaimer(text: str) -> str:
    disclaimer = get_settings().disclaimer
    if disclaimer in text:
        return text
    return f"{text.strip()}\n\n{disclaimer}"


def has_disclaimer(text: str) -> bool:
    return get_settings().disclaimer in text


def citation_coverage_score(answer_text: str, citations: list[object]) -> float:
    claims = decompose_claims(answer_text)
    result = ground_claims(claims, citations)
    return claim_coverage_score(result)


def post_answer_policy(answer_text: str, citations: list[object]) -> tuple[bool, list[str], float]:
    gaps: list[str] = []
    coverage = citation_coverage_score(answer_text, citations)
    claims = decompose_claims(answer_text)
    grounding = ground_claims(claims, citations)

    if len(citations) == 0:
        gaps.append("No citations found for generated answer.")
    if coverage < 0.5:
        gaps.append("Low claim-level citation coverage.")
    if grounding.ungrounded_claims:
        gaps.append("Ungrounded declarative claims detected.")
    if not has_disclaimer(answer_text):
        gaps.append("Missing mandatory disclaimer.")
    return len(gaps) == 0, gaps, coverage
