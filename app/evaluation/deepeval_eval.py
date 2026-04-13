"""DeepEval-style evaluation harness with graceful degradation.

DeepEval ships unit-test-like LLM metrics. We use the same three-tier
strategy as ``ragas_eval``:

1. **Real DeepEval** — only when ``OPENAI_API_KEY`` is set and the
   ``deepeval`` package can build a model. Computes hallucination,
   answer_relevancy and faithfulness.
2. **Heuristic proxy** — lexical-overlap based scoring so that the
   evaluation report still ships numeric DeepEval metrics in CI.
3. **Not run** — empty sample list.
"""

from __future__ import annotations

import logging
import os
import re
from typing import Any

logger = logging.getLogger(__name__)

_TOKEN_RE = re.compile(r"[a-zçğıöşü0-9]+", re.IGNORECASE)


def _tokens(text: str) -> set[str]:
    if not text:
        return set()
    return {match.group(0).lower() for match in _TOKEN_RE.finditer(text)}


def deepeval_available() -> bool:
    return bool(os.environ.get("OPENAI_API_KEY"))


def _heuristic_metrics(samples: list[dict[str, Any]]) -> dict[str, float]:
    if not samples:
        return {
            "hallucination_rate": 0.0,
            "answer_relevancy": 0.0,
            "faithfulness": 0.0,
        }

    hallucination_scores: list[float] = []
    relevancy_scores: list[float] = []
    faithfulness_scores: list[float] = []

    for sample in samples:
        question = _tokens(sample.get("question", ""))
        answer = _tokens(sample.get("answer", ""))
        contexts = " ".join(str(ctx) for ctx in (sample.get("contexts") or []))
        context_tokens = _tokens(contexts)

        if answer:
            grounded = len(answer & context_tokens) / len(answer)
        else:
            grounded = 0.0

        # Hallucination is the inverse of grounding.
        hallucination_scores.append(round(1.0 - grounded, 4))
        # Answer relevancy ~ overlap with question
        if question:
            relevancy_scores.append(round(len(answer & question) / len(question), 4))
        else:
            relevancy_scores.append(0.0)
        faithfulness_scores.append(round(grounded, 4))

    def _avg(values: list[float]) -> float:
        return round(sum(values) / len(values), 4) if values else 0.0

    return {
        "hallucination_rate": _avg(hallucination_scores),
        "answer_relevancy": _avg(relevancy_scores),
        "faithfulness": _avg(faithfulness_scores),
    }


def _try_real_deepeval(samples: list[dict[str, Any]]) -> dict[str, Any] | None:
    try:
        from deepeval import evaluate  # type: ignore
        from deepeval.metrics import (  # type: ignore
            AnswerRelevancyMetric,
            FaithfulnessMetric,
            HallucinationMetric,
        )
        from deepeval.test_case import LLMTestCase  # type: ignore
    except Exception as exc:  # noqa: BLE001
        logger.info("DeepEval real path unavailable: %s", exc)
        return None

    try:
        test_cases = []
        for sample in samples:
            test_cases.append(
                LLMTestCase(
                    input=sample.get("question", ""),
                    actual_output=sample.get("answer", ""),
                    retrieval_context=sample.get("contexts") or [],
                    context=sample.get("contexts") or [],
                    expected_output=sample.get("ground_truth") or "",
                )
            )
        metrics = [
            HallucinationMetric(threshold=0.5),
            AnswerRelevancyMetric(threshold=0.5),
            FaithfulnessMetric(threshold=0.5),
        ]
        result = evaluate(test_cases=test_cases, metrics=metrics)
        scores: dict[str, float] = {}
        for case in getattr(result, "test_results", []) or []:
            for metric in getattr(case, "metrics_data", []) or []:
                name = getattr(metric, "name", "metric")
                score = float(getattr(metric, "score", 0.0))
                scores.setdefault(name, []).append(score)  # type: ignore[union-attr]
        averaged = {
            name: round(sum(values) / len(values), 4) if values else 0.0  # type: ignore[arg-type]
            for name, values in scores.items()
        }
        return {
            "status": "ok",
            "mode": "deepeval_real",
            "metrics": averaged,
            "n_samples": len(samples),
        }
    except Exception as exc:  # noqa: BLE001
        logger.warning("DeepEval real evaluation failed: %s", exc)
        return None


def run_deepeval_evaluation(samples: list[dict[str, Any]]) -> dict[str, Any]:
    if not samples:
        return {"status": "not_run", "reason": "empty_sample_set", "metrics": {}}

    if deepeval_available():
        real = _try_real_deepeval(samples)
        if real is not None:
            return real
        logger.info("Falling back to DeepEval heuristic proxy.")

    metrics = _heuristic_metrics(samples)
    return {
        "status": "ok",
        "mode": "deepeval_heuristic_proxy",
        "metrics": metrics,
        "n_samples": len(samples),
        "reason": "no_api_key_or_deepeval_unavailable",
    }
