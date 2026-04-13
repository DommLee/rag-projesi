from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.models.providers import RoutedLLM
from app.schemas import QueryRequest, QueryResponse
from app.utils.text import normalize_visible_text


@dataclass(frozen=True)
class DebatePerspective:
    key: str
    label: str
    instruction: str


class DebateOrchestrator:
    PERSPECTIVES = (
        DebatePerspective("official_evidence", "Official Evidence", "Only evaluate official/KAP-style evidence and identify what is confirmed."),
        DebatePerspective("risk_framing", "Risk Framing", "Identify uncertainty, weak evidence, contradictions, and missing citations without giving advice."),
        DebatePerspective("neutral_synthesis", "Neutral Synthesis", "Summarize the most defensible neutral interpretation using citations only."),
    )

    def __init__(self, llm: RoutedLLM) -> None:
        self.llm = llm

    def _run_perspective(self, request: QueryRequest, response: QueryResponse, perspective: DebatePerspective) -> dict[str, Any]:
        citation_lines = [
            f"- {c.source_type.value} | {c.institution} | {c.date.date()} | {c.title}: {c.snippet[:180]}"
            for c in response.citations[:8]
        ]
        prompt = f"""
You are a non-advisory BIST evidence reviewer.
Perspective: {perspective.label}
Instruction: {perspective.instruction}
Ticker: {request.ticker}
Question: {request.question}
Base TR answer: {response.answer_tr}
Base EN answer: {response.answer_en}
Citations:
{chr(10).join(citation_lines) if citation_lines else "No citations"}

Return concise Turkish bullets. Do not provide buy/sell signals, target prices, or return forecasts.
"""
        try:
            text, provider = self.llm.generate_with_provider(
                prompt,
                provider_pref=request.provider_pref,
                provider_overrides=request.provider_overrides,
            )
            return {
                "key": perspective.key,
                "label": perspective.label,
                "provider": provider,
                "view": normalize_visible_text(text)[:1200],
            }
        except Exception as exc:  # noqa: BLE001
            return {
                "key": perspective.key,
                "label": perspective.label,
                "provider": "heuristic",
                "view": f"Model unavailable; heuristic note: {response.consistency_assessment}, citation coverage {response.citation_coverage_score:.2f}. Error: {exc}",
            }

    @staticmethod
    def _consensus(response: QueryResponse, perspectives: list[dict[str, Any]]) -> dict[str, Any]:
        if response.blocked:
            status = "blocked_policy"
        elif response.citation_coverage_score < 0.5:
            status = "insufficient_evidence"
        elif response.consistency_assessment == "contradiction":
            status = "contradiction"
        else:
            status = "usable_with_citations"
        common_points = [
            f"Base consistency: {response.consistency_assessment}",
            f"Citation coverage: {response.citation_coverage_score:.2f}",
            f"Citation count: {len(response.citations)}",
        ]
        conflicting_points = response.evidence_gaps[:8]
        return {
            "status": status,
            "common_points": common_points,
            "conflicting_or_weak_points": conflicting_points,
            "final_note_tr": (
                "Debate sonucu kanıt temelli ve tavsiye içermeyen sentez kullanılabilir."
                if status == "usable_with_citations"
                else "Debate sonucu kanıt boşlukları nedeniyle temkinli/inconclusive modda tutulmalıdır."
            ),
        }

    def run(self, request: QueryRequest, response: QueryResponse) -> dict[str, Any]:
        perspectives = [self._run_perspective(request, response, item) for item in self.PERSPECTIVES]
        return {
            "ticker": request.ticker,
            "question": request.question,
            "base_response": response.model_dump(mode="json"),
            "perspectives": perspectives,
            "consensus": self._consensus(response, perspectives),
            "disclaimer": "This system does not provide investment advice.",
        }

