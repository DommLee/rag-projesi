from __future__ import annotations

import unicodedata
from collections import Counter, defaultdict
from datetime import UTC
from typing import Any

import numpy as np

from app.models.embeddings import embed_text
from app.schemas import DocumentChunk, SourceType


CONTRADICTION_CUES = {
    "olumlu": {"artış", "güçlü", "iyileşme", "onay"},
    "olumsuz": {"azalış", "zayıf", "iptal", "ceza", "reddedildi"},
}


def _normalize_token(token: str) -> str:
    normalized = unicodedata.normalize("NFC", token.strip().lower())
    return "".join(ch for ch in normalized if ch.isalnum())


def _tokenize(text: str) -> list[str]:
    return [_normalize_token(tok) for tok in text.split() if _normalize_token(tok)]


def narrative_drift_radar(chunks: list[DocumentChunk]) -> dict[str, Any]:
    by_week: dict[str, list[np.ndarray]] = defaultdict(list)
    for chunk in chunks:
        dt = chunk.date.astimezone(UTC)
        week_key = f"{dt.year}-W{dt.isocalendar().week:02d}"
        by_week[week_key].append(np.array(embed_text(chunk.content)))

    ordered = sorted(by_week.items(), key=lambda x: x[0])
    drift = []
    for idx in range(1, len(ordered)):
        prev_key, prev_vectors = ordered[idx - 1]
        curr_key, curr_vectors = ordered[idx]
        prev_mean = np.mean(prev_vectors, axis=0)
        curr_mean = np.mean(curr_vectors, axis=0)
        prev_mean = prev_mean / (np.linalg.norm(prev_mean) or 1.0)
        curr_mean = curr_mean / (np.linalg.norm(curr_mean) or 1.0)
        similarity = float(np.dot(prev_mean, curr_mean))
        drift.append({"from": prev_key, "to": curr_key, "drift_score": round(1 - similarity, 4)})
    return {"weekly_drift": drift}


def disclosure_news_tension_index(chunks: list[DocumentChunk]) -> dict[str, Any]:
    kap_text = " ".join(c.content for c in chunks if c.source_type == SourceType.KAP)
    news_text = " ".join(c.content for c in chunks if c.source_type == SourceType.NEWS)
    if not kap_text or not news_text:
        return {"tension_index": 0.0, "reason": "insufficient_cross_source_data"}

    kap_tokens = set(_tokenize(kap_text))
    news_tokens = set(_tokenize(news_text))
    shared = kap_tokens.intersection(news_tokens)
    total = len(kap_tokens.union(news_tokens)) or 1
    lexical_overlap = len(shared) / total

    kap_pos = len(kap_tokens.intersection(CONTRADICTION_CUES["olumlu"]))
    kap_neg = len(kap_tokens.intersection(CONTRADICTION_CUES["olumsuz"]))
    news_pos = len(news_tokens.intersection(CONTRADICTION_CUES["olumlu"]))
    news_neg = len(news_tokens.intersection(CONTRADICTION_CUES["olumsuz"]))

    polarity_gap = abs((kap_pos - kap_neg) - (news_pos - news_neg))
    tension = min(1.0, (1 - lexical_overlap) * 0.6 + min(polarity_gap / 10, 1.0) * 0.4)
    return {"tension_index": round(tension, 4), "lexical_overlap": round(lexical_overlap, 4)}


def broker_bias_lens(chunks: list[DocumentChunk], top_terms: int = 8) -> dict[str, Any]:
    by_institution: dict[str, Counter] = defaultdict(Counter)
    for chunk in chunks:
        if chunk.source_type != SourceType.BROKERAGE:
            continue
        by_institution[chunk.institution].update(_tokenize(chunk.content))

    profile: dict[str, Any] = {}
    for institution, counter in by_institution.items():
        profile[institution] = counter.most_common(top_terms)

    institutions = list(profile.keys())
    divergence: dict[str, float] = {}
    if len(institutions) >= 2:
        base_terms = {term for term, _ in profile[institutions[0]]}
        for other in institutions[1:]:
            other_terms = {term for term, _ in profile[other]}
            jaccard = len(base_terms.intersection(other_terms)) / (len(base_terms.union(other_terms)) or 1)
            divergence[f"{institutions[0]}_vs_{other}"] = round(1 - jaccard, 4)

    return {"theme_profile": profile, "wording_divergence": divergence}

