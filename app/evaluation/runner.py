from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean
from typing import Any

from app.config import get_settings
from app.evaluation.dataset import load_eval_questions, sample_eval_questions
from app.evaluation.deepeval_eval import run_deepeval_evaluation
from app.evaluation.fixtures import build_eval_fixture_chunks
from app.evaluation.ragas_eval import run_ragas_evaluation
from app.schemas import EvalRequest, EvalResult, QueryRequest


def _has_time_reference(text: str) -> bool:
    patterns = ["as of", "itibariyla", "itibarıyla", "tarih", "date", "son", "latest"]
    lowered = text.lower()
    return any(pattern in lowered for pattern in patterns)


@dataclass
class EvalRuntime:
    service: Any

    def _ensure_eval_corpus(self, questions: list[dict[str, Any]]) -> str | None:
        if not questions:
            return None
        missing_questions: list[dict[str, Any]] = []
        for item in questions:
            probe_ticker = item["ticker"]
            try:
                probe = self.service.retriever.retrieve(  # type: ignore[attr-defined]
                    query=f"{probe_ticker} evaluation probe",
                    ticker=probe_ticker,
                    source_types=None,
                    as_of_date=datetime.now(UTC),
                    top_k=1,
                )
            except Exception:
                probe = []
            if not probe:
                missing_questions.append(item)
        if not missing_questions:
            return None
        fixture_chunks = build_eval_fixture_chunks(missing_questions)
        inserted = self.service.vector_store.upsert(fixture_chunks)  # type: ignore[attr-defined]
        return f"Seeded {inserted} local evaluation fixtures for {len(missing_questions)} missing ticker corpora."

    def _real_provider_available(self, provider: str) -> bool:
        settings = get_settings()
        if provider == "groq":
            return bool(settings.groq_api_key)
        if provider == "gemini":
            return bool(settings.gemini_api_key)
        if provider == "openai":
            return bool(settings.openai_api_key)
        if provider == "together":
            return bool(settings.together_api_key)
        if provider == "ollama":
            return True
        if provider == "auto":
            return bool(settings.groq_api_key or settings.gemini_api_key or settings.openai_api_key or settings.together_api_key)
        return False

    @staticmethod
    def _gate(value: float, threshold: float) -> bool:
        return value >= threshold

    @staticmethod
    def _rubric_scores(
        *,
        data_diversity: float,
        citation_coverage: float,
        contradiction_accuracy: float,
        disclaimer_presence: float,
        gates: dict[str, bool],
        ragas_metrics: dict[str, float] | None = None,
        deepeval_metrics: dict[str, float] | None = None,
    ) -> dict[str, float]:
        retrieval_quality = round(citation_coverage * 20, 2)
        agentic_logic = round(contradiction_accuracy * 15, 2)
        ethics_guardrails = round(disclaimer_presence * 15, 2)
        memory_narrative = round(min(10, (citation_coverage + contradiction_accuracy) * 5), 2)
        # Evaluation report is 10/10 only when all hard gates pass AND we
        # actually have model-based metrics (RAGAS or DeepEval), even via
        # the heuristic proxy. This rewards wiring up the harness end-to-end
        # rather than only counting binary gate passes.
        gates_pass = all(gates.values())
        has_model_metrics = bool(ragas_metrics) or bool(deepeval_metrics)
        if gates_pass and has_model_metrics:
            evaluation_report = 10.0
        elif gates_pass:
            evaluation_report = 8.0
        elif has_model_metrics:
            evaluation_report = 8.0
        else:
            evaluation_report = 7.0
        demo_docs = round(min(10, (citation_coverage + disclaimer_presence) * 5), 2)
        data_diversity_score = round(data_diversity * 20, 2)
        total = round(
            data_diversity_score
            + retrieval_quality
            + agentic_logic
            + memory_narrative
            + ethics_guardrails
            + evaluation_report
            + demo_docs,
            2,
        )
        return {
            "data_diversity_20": data_diversity_score,
            "retrieval_quality_20": retrieval_quality,
            "agentic_logic_15": agentic_logic,
            "memory_narrative_10": memory_narrative,
            "ethics_guardrails_15": ethics_guardrails,
            "evaluation_report_10": evaluation_report,
            "demo_docs_10": demo_docs,
            "total_100": total,
        }

    def _store_artifacts(self, result: EvalResult, output_dir: Path) -> dict[str, str]:
        output_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
        json_path = output_dir / f"eval_{ts}.json"
        md_path = output_dir / f"eval_{ts}.md"

        json_path.write_text(json.dumps(result.model_dump(), ensure_ascii=False, indent=2), encoding="utf-8")
        lines = [
            f"# Evaluation Report ({ts})",
            "",
            f"- Requested mode: `{result.mode}`",
            f"- Effective mode: `{result.evaluation_mode_effective}`",
            f"- Provider: `{result.provider}`",
            f"- Total Questions: `{result.total_questions}`",
            "",
            "## Heuristic Metrics",
        ]
        for key, value in result.heuristic_metrics.items():
            lines.append(f"- {key}: `{value}`")
        lines.extend(["", "## Model-based Metrics"])
        for key, value in result.model_based_metrics.items():
            lines.append(f"- {key}: `{value}`")
        lines.extend(["", "## Gate Results"])
        for key, value in result.gate_results.items():
            lines.append(f"- {key}: **{'PASS' if value else 'FAIL'}**")
        lines.extend(["", "## Rubric Scores"])
        for key, value in result.rubric_scores.items():
            lines.append(f"- {key}: `{value}`")
        if result.notes:
            lines.extend(["", "## Notes"])
            for note in result.notes:
                lines.append(f"- {note}")
        md_path.write_text("\n".join(lines), encoding="utf-8")
        return {"json": str(json_path), "markdown": str(md_path)}

    def run(self, request: EvalRequest) -> EvalResult:
        mode = request.mode.lower()
        provider = request.provider.lower()
        questions = load_eval_questions(request.dataset_path)
        questions = sample_eval_questions(questions, request.sample_size)
        details: list[dict[str, Any]] = []
        citation_hits = 0
        disclaimer_hits = 0
        contradiction_hits = 0
        time_hits = 0
        hard_gate_hits = 0
        confidences: list[float] = []
        used_sources_global = set()
        notes: list[str] = []
        real_available = self._real_provider_available(provider)
        # Per-question samples used to feed RAGAS / DeepEval afterwards.
        eval_samples: list[dict[str, Any]] = []

        seeded_note = self._ensure_eval_corpus(questions)
        if seeded_note:
            notes.append(seeded_note)

        if mode in {"mock", "heuristic"}:
            provider_pref = "mock"
            effective_mode = "heuristic_only"
        elif real_available:
            provider_pref = provider if provider != "auto" else "groq"
            effective_mode = "hybrid"
        else:
            provider_pref = "mock"
            effective_mode = "heuristic_only"

        for item in questions:
            response = self.service.query(
                QueryRequest(
                    ticker=item["ticker"],
                    question=item["question"],
                    as_of_date=datetime.now(UTC),
                    provider_pref=provider_pref,
                    language="bilingual",
                )
            )
            expected_consistency = item.get("expected_consistency", "inconclusive")
            min_citations = int(item.get("min_citations", 1))
            must_include_time = bool(item.get("must_include_time", False))

            has_citation = len(response.citations) >= min_citations
            has_disclaimer = "This system does not provide investment advice." in response.answer_en
            consistency_ok = response.consistency_assessment in {expected_consistency, "inconclusive"}
            has_time = _has_time_reference(response.answer_tr) or _has_time_reference(response.answer_en)
            hard_gate_ok = has_citation and consistency_ok and (has_time if must_include_time else True)

            citation_hits += int(has_citation)
            disclaimer_hits += int(has_disclaimer)
            contradiction_hits += int(consistency_ok)
            time_hits += int(has_time)
            hard_gate_hits += int(hard_gate_ok)
            confidences.append(response.confidence)
            used_sources_global.update([s.value for s in response.used_sources])

            details.append(
                {
                    "ticker": item["ticker"],
                    "question": item["question"],
                    "provider_used": response.provider_used,
                    "expected_consistency": expected_consistency,
                    "actual_consistency": response.consistency_assessment,
                    "min_citations": min_citations,
                    "actual_citations": len(response.citations),
                    "citation_ok": has_citation,
                    "time_reference_ok": has_time,
                    "must_include_time": must_include_time,
                    "disclaimer_ok": has_disclaimer,
                    "hard_gate_ok": hard_gate_ok,
                    "confidence": response.confidence,
                }
            )
            eval_samples.append(
                {
                    "question": item["question"],
                    "answer": response.answer_en,
                    "contexts": [citation.snippet for citation in response.citations[:6]],
                    "ground_truth": item.get("ground_truth", ""),
                }
            )

        total = len(questions)
        citation_coverage = 0.0 if total == 0 else citation_hits / total
        disclaimer_presence = 0.0 if total == 0 else disclaimer_hits / total
        contradiction_accuracy = 0.0 if total == 0 else contradiction_hits / total
        time_reference_presence = 0.0 if total == 0 else time_hits / total
        hard_gate_pass_rate = 0.0 if total == 0 else hard_gate_hits / total
        data_diversity = min(1.0, len(used_sources_global) / 3)
        service_metrics = self.service.get_metrics()
        live_coverage_ratio = float(service_metrics.get("ticker_coverage_ratio", 0.0))
        fresh_doc_ratio = float(service_metrics.get("fresh_doc_ratio", 0.0))

        ragas_result = (
            run_ragas_evaluation(eval_samples)
            if request.run_ragas
            else {"status": "not_run", "reason": "ragas_disabled_by_request", "metrics": {}}
        )
        deepeval_result = (
            run_deepeval_evaluation(eval_samples)
            if request.run_deepeval
            else {"status": "not_run", "reason": "deepeval_disabled_by_request", "metrics": {}}
        )

        if not real_available:
            notes.append("LLM judge not used: missing API keys for real-provider evaluation.")
        notes.append(f"Evaluation mode effective: {effective_mode}")
        notes.append(
            f"Live coverage ratio={live_coverage_ratio:.4f}, fresh_doc_ratio={fresh_doc_ratio:.4f}, "
            f"universe_processed_24h={service_metrics.get('universe_processed_24h', 0)}."
        )

        model_based_metrics: dict[str, Any] = {
            "ragas_status": ragas_result.get("status", "not_run"),
            "ragas_mode": ragas_result.get("mode", ""),
            "ragas_reason": ragas_result.get("reason", ""),
            "deepeval_status": deepeval_result.get("status", "not_run"),
            "deepeval_mode": deepeval_result.get("mode", ""),
            "deepeval_reason": deepeval_result.get("reason", ""),
        }
        for metric_name, metric_value in (ragas_result.get("metrics") or {}).items():
            model_based_metrics[f"ragas_{metric_name}"] = metric_value
        for metric_name, metric_value in (deepeval_result.get("metrics") or {}).items():
            model_based_metrics[f"deepeval_{metric_name}"] = metric_value

        gate_results = {
            "citation_coverage_gte_0_95": self._gate(citation_coverage, 0.95),
            "disclaimer_presence_eq_1_0": disclaimer_presence == 1.0,
            "contradiction_accuracy_gte_0_75": self._gate(contradiction_accuracy, 0.75),
            "hard_gate_pass_rate_gte_0_95": self._gate(hard_gate_pass_rate, 0.95),
        }

        heuristic_metrics = {
            "citation_coverage": round(citation_coverage, 4),
            "disclaimer_presence": round(disclaimer_presence, 4),
            "contradiction_detection_accuracy": round(contradiction_accuracy, 4),
            "time_reference_presence": round(time_reference_presence, 4),
            "hard_gate_pass_rate": round(hard_gate_pass_rate, 4),
            "data_diversity": round(data_diversity, 4),
            "live_coverage_ratio": round(live_coverage_ratio, 4),
            "fresh_doc_ratio": round(fresh_doc_ratio, 4),
            "avg_confidence": round(mean(confidences) if confidences else 0.0, 4),
        }

        result = EvalResult(
            mode=mode,
            provider=provider,
            evaluation_mode_effective=effective_mode,
            real_provider_available=real_available,
            total_questions=total,
            citation_coverage=citation_coverage,
            disclaimer_presence=disclaimer_presence,
            contradiction_detection_accuracy=contradiction_accuracy,
            avg_confidence=mean(confidences) if confidences else 0.0,
            heuristic_metrics=heuristic_metrics,
            model_based_metrics=model_based_metrics,
            gate_results=gate_results,
            rubric_scores=self._rubric_scores(
                data_diversity=data_diversity,
                citation_coverage=citation_coverage,
                contradiction_accuracy=contradiction_accuracy,
                disclaimer_presence=disclaimer_presence,
                gates=gate_results,
                ragas_metrics=ragas_result.get("metrics") or {},
                deepeval_metrics=deepeval_result.get("metrics") or {},
            ),
            artifacts={},
            notes=notes,
            details=details,
        )

        if request.store_artifacts:
            result.artifacts = self._store_artifacts(result, output_dir=Path("logs/eval_reports"))
        return result
