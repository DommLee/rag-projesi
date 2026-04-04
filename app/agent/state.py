from __future__ import annotations

from datetime import datetime
from typing import TypedDict

from app.schemas import Citation, DocumentChunk, SourceType


class AgentState(TypedDict, total=False):
    ticker: str
    question: str
    as_of_date: datetime | None
    language: str
    provider_pref: str | None
    session_id: str

    risk_blocked: bool
    question_type: str
    source_plan: list[SourceType]
    source_weights: dict[str, float]

    pass1_docs: list[DocumentChunk]
    pass2_docs: list[DocumentChunk]
    counterfactual_docs: list[DocumentChunk]

    evidence_coverage: float
    contradiction_confidence: float
    consistency_assessment: str

    citations: list[Citation]
    answer_tr: str
    answer_en: str
    confidence: float
    evidence_gaps: list[str]
    citation_coverage_score: float
    provider_used: str
    retrieval_trace: dict
