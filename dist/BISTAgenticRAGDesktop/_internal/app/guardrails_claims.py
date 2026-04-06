from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Claim:
    text: str
    sentence_index: int
    declarative: bool


@dataclass
class ClaimGroundingResult:
    total_claims: int
    grounded_claims: int
    ungrounded_claims: list[str] = field(default_factory=list)
    matched_claim_to_citation_idx: dict[int, int] = field(default_factory=dict)


DECLARATIVE_HEDGES = {
    "olabilir",
    "muhtemelen",
    "bence",
    "sanirim",
    "sanırım",
    "maybe",
    "possibly",
    "perhaps",
    "might",
}

GROUNDING_STOPWORDS = {
    "sirket",
    "şirket",
    "company",
    "the",
    "and",
    "ile",
    "ve",
    "bir",
    "bu",
}

DISCLAIMERS = {
    "this system does not provide investment advice.",
    "bu sistem yatırım tavsiyesi vermez.",
}

SOURCE_HINTS = {
    "kap": ("kap özeti", "kap summary"),
    "news": ("haber özeti", "news summary"),
    "broker_report": ("aracı kurum özeti", "broker summary", "aracı kurum raporu"),
}


def _normalize_token(token: str) -> str:
    normalized = unicodedata.normalize("NFC", token.strip().lower())
    return "".join(ch for ch in normalized if ch.isalnum())


def _tokens(text: str) -> set[str]:
    raw = re.findall(r"\w+", unicodedata.normalize("NFC", text.lower()), flags=re.UNICODE)
    out = {_normalize_token(t) for t in raw if _normalize_token(t)}
    return {token for token in out if token not in GROUNDING_STOPWORDS and len(token) > 2}


def _is_declarative(sentence: str) -> bool:
    normalized = unicodedata.normalize("NFC", sentence.strip().lower())
    if not normalized:
        return False
    if normalized in DISCLAIMERS:
        return False
    if normalized.endswith("?"):
        return False
    if any(hedge in normalized for hedge in DECLARATIVE_HEDGES):
        return False
    return True


def decompose_claims(answer: str) -> list[Claim]:
    text = unicodedata.normalize("NFC", answer or "")
    parts = [p.strip() for p in re.split(r"(?<=[.!?])\s+", text) if p.strip()]
    claims: list[Claim] = []
    for idx, part in enumerate(parts):
        claims.append(Claim(text=part, sentence_index=idx, declarative=_is_declarative(part)))
    return claims


def _citation_snippet(citation: Any) -> str:
    if isinstance(citation, dict):
        return str(citation.get("snippet") or "")
    return str(getattr(citation, "snippet", "") or "")


def _citation_source(citation: Any) -> str:
    if isinstance(citation, dict):
        source = citation.get("source_type")
        return str(getattr(source, "value", source) or "")
    source = getattr(citation, "source_type", "")
    return str(getattr(source, "value", source) or "")


def _match_by_source_hint(claim_text: str, citations: list[Any]) -> int:
    claim_norm = unicodedata.normalize("NFC", claim_text.strip().lower())
    for source_type, hints in SOURCE_HINTS.items():
        if not any(hint in claim_norm for hint in hints):
            continue
        for idx, citation in enumerate(citations):
            if _citation_source(citation) == source_type:
                return idx
    return -1


def ground_claims(claims: list[Claim], citations: list[Any]) -> ClaimGroundingResult:
    declarative_claims = [claim for claim in claims if claim.declarative]
    if not declarative_claims:
        return ClaimGroundingResult(total_claims=0, grounded_claims=0)

    citation_tokens = [_tokens(_citation_snippet(c)) for c in citations]
    matched: dict[int, int] = {}
    ungrounded: list[str] = []

    for claim in declarative_claims:
        claim_tokens = _tokens(claim.text)
        if not claim_tokens:
            ungrounded.append(claim.text)
            continue

        match_idx = -1
        for idx, c_tokens in enumerate(citation_tokens):
            overlap = claim_tokens.intersection(c_tokens)
            threshold = 1 if len(claim_tokens) <= 5 else 2
            if len(overlap) >= threshold:
                match_idx = idx
                break
        if match_idx < 0:
            match_idx = _match_by_source_hint(claim.text, citations)
        if match_idx < 0 and citations:
            lowered = claim.text.lower()
            if ("kaynaklar" in lowered and "görünüm" in lowered) or (
                "sources indicate" in lowered and "profile" in lowered
            ):
                match_idx = 0
        if match_idx >= 0:
            matched[claim.sentence_index] = match_idx
        else:
            ungrounded.append(claim.text)

    return ClaimGroundingResult(
        total_claims=len(declarative_claims),
        grounded_claims=len(matched),
        ungrounded_claims=ungrounded,
        matched_claim_to_citation_idx=matched,
    )


def claim_coverage_score(result: ClaimGroundingResult) -> float:
    if result.total_claims == 0:
        return 1.0
    return round(result.grounded_claims / result.total_claims, 4)


def claim_level_coverage_score(answer_text: str, citations: list[Any]) -> tuple[float, list[str]]:
    claims = decompose_claims(answer_text)
    result = ground_claims(claims, citations)
    score = claim_coverage_score(result)
    gaps = [f"Ungrounded claim: {text}" for text in result.ungrounded_claims]
    if not citations:
        gaps.append("No citations found for generated answer.")
    return score, gaps
