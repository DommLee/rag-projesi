from __future__ import annotations

import re
from dataclasses import dataclass

from app.config import get_settings


INVESTMENT_ADVICE_PATTERNS = [
    r"\b(al|sat|tut)\b",
    r"\bbuy\b",
    r"\bsell\b",
    r"hedef fiyat",
    r"price target",
    r"kaç olur",
    r"yükselir mi",
    r"düşer mi",
    r"return prediction",
    r"getiri tahmini",
]


@dataclass
class PolicyDecision:
    allowed: bool
    reason: str
    refusal_tr: str = ""
    refusal_en: str = ""


def pre_answer_policy(question: str) -> PolicyDecision:
    text = question.lower()
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


def _split_sentences(text: str) -> list[str]:
    return [sentence.strip() for sentence in re.split(r"[.!?]+", text) if sentence.strip()]


def citation_coverage_score(answer_text: str, citations_count: int) -> float:
    sentences = _split_sentences(answer_text)
    if not sentences:
        return 0.0
    if citations_count == 0:
        return 0.0
    # Approximate sentence-level evidence: more citations imply better coverage.
    covered = min(len(sentences), citations_count)
    return round(covered / len(sentences), 4)


def post_answer_policy(answer_text: str, citations_count: int) -> tuple[bool, list[str], float]:
    gaps: list[str] = []
    coverage = citation_coverage_score(answer_text, citations_count)
    if citations_count == 0:
        gaps.append("No citations found for generated answer.")
    if coverage < 0.5:
        gaps.append("Low sentence-level citation coverage.")
    if not has_disclaimer(answer_text):
        gaps.append("Missing mandatory disclaimer.")
    return len(gaps) == 0, gaps, coverage

