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
    provider_overrides: dict[str, str] | None
    session_id: str

    risk_blocked: bool
    skip_to_composer: bool
    question_type: str
    source_plan: list[SourceType]
    source_weights: dict[str, float]

    pass1_docs: list[DocumentChunk]
    pass2_docs: list[DocumentChunk]
    counterfactual_docs: list[DocumentChunk]

    evidence_coverage: float
    contradiction_confidence: float
    rule_tension: float
    llm_tension: float
    tension_mode: str
    should_reretrieve: bool
    consistency_assessment: str

    citations: list[Citation]
    answer_tr: str
    answer_en: str
    confidence: float
    evidence_gaps: list[str]
    citation_coverage_score: float
    provider_used: str
    rewritten_question: str
    reflection_applied: bool
    retrieval_trace: dict
    web_search_results: list[dict]
    graph_context: dict
