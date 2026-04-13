"""RAGAS-style evaluation harness with graceful degradation.

Three modes are supported, picked automatically:

1. **Real RAGAS**     — only when ``OPENAI_API_KEY`` is set AND the
   ``ragas`` package can build a judge LLM. Computes faithfulness,
   answer_relevancy, context_precision and context_recall.
2. **Heuristic proxy** — no API key but at least one sample. Computes
   lexical-overlap proxies for the same four metrics so that an
   evaluation report can still ship a numeric RAGAS section. Clearly
   labelled as a proxy in the result payload.
3. **Not run**         — empty sample list.

The function signature stays compatible with the previous version
(``run_ragas_evaluation(samples)``) so the runner does not need to
change. Each ``sample`` is a dict shaped like::

    {
        "question": str,
        "answer":   str,
        "contexts": list[str],
        "ground_truth": str | None,
    }
"""

from __future__ import annotations

import logging
import os
import re
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------- #
# Helpers
# ---------------------------------------------------------------------- #
_TOKEN_RE = re.compile(r"[a-zçğıöşü0-9]+", re.IGNORECASE)


def _tokens(text: str) -> set[str]:
    if not text:
        return set()
    return {match.group(0).lower() for match in _TOKEN_RE.finditer(text)}


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    return 0.0 if union == 0 else inter / union


def _coverage(reference: set[str], evidence: set[str]) -> float:
    if not reference:
        return 0.0
    return len(reference & evidence) / len(reference)


def ragas_available() -> bool:
    return bool(os.environ.get("OPENAI_API_KEY"))


# ---------------------------------------------------------------------- #
# Heuristic proxy implementation
# ---------------------------------------------------------------------- #
def _heuristic_metrics(samples: list[dict[str, Any]]) -> dict[str, float]:
    if not samples:
        return {
            "faithfulness": 0.0,
            "answer_relevancy": 0.0,
            "context_precision": 0.0,
            "context_recall": 0.0,
        }

    faithfulness_scores: list[float] = []
    relevancy_scores: list[float] = []
    precision_scores: list[float] = []
    recall_scores: list[float] = []

    for sample in samples:
        question_tokens = _tokens(sample.get("question", ""))
        answer_tokens = _tokens(sample.get("answer", ""))
        contexts = sample.get("contexts") or []
        context_text = " ".join(str(ctx) for ctx in contexts)
        context_tokens = _tokens(context_text)
        gt_tokens = _tokens(sample.get("ground_truth") or "")

        # Faithfulness ~ how much of the answer is grounded in retrieved context
        faithfulness_scores.append(_coverage(answer_tokens, context_tokens))
        # Answer relevancy ~ overlap between answer and the question
        relevancy_scores.append(_jaccard(answer_tokens, question_tokens))
        # Context precision ~ how much of the context tokens appear in the answer
        precision_scores.append(_coverage(context_tokens, answer_tokens))
        # Context recall ~ overlap between the (optional) ground truth and the answer
        if gt_tokens:
            recall_scores.append(_coverage(gt_tokens, answer_tokens))

    def _avg(values: list[float]) -> float:
        return round(sum(values) / len(values), 4) if values else 0.0

    return {
        "faithfulness": _avg(faithfulness_scores),
        "answer_relevancy": _avg(relevancy_scores),
        "context_precision": _avg(precision_scores),
        "context_recall": _avg(recall_scores),
    }


# ---------------------------------------------------------------------- #
# Real RAGAS path
# ---------------------------------------------------------------------- #
def _try_real_ragas(samples: list[dict[str, Any]]) -> dict[str, Any] | None:
    try:
        from ragas import evaluate  # type: ignore
        from ragas.metrics import (  # type: ignore
            answer_relevancy,
            context_precision,
            context_recall,
            faithfulness,
        )

        from datasets import Dataset  # type: ignore
    except Exception as exc:  # noqa: BLE001
        logger.info("RAGAS real path unavailable: %s", exc)
        return None

    try:
        dataset = Dataset.from_list(
            [
                {
                    "question": sample.get("question", ""),
                    "answer": sample.get("answer", ""),
                    "contexts": sample.get("contexts") or [],
                    "ground_truth": sample.get("ground_truth") or "",
                }
                for sample in samples
            ]
        )
        metrics = [faithfulness, answer_relevancy, context_precision]
        # context_recall needs ground_truth for every row
        if all((sample.get("ground_truth") or "") for sample in samples):
            metrics.append(context_recall)
        result = evaluate(dataset=dataset, metrics=metrics)
        scores = {key: round(float(value), 4) for key, value in result.items() if isinstance(value, (int, float))}
        return {
            "status": "ok",
            "mode": "ragas_real",
            "metrics": scores,
            "n_samples": len(samples),
        }
    except Exception as exc:  # noqa: BLE001
        logger.warning("RAGAS real evaluation failed: %s", exc)
        return None


# ---------------------------------------------------------------------- #
# Public entry point
# ---------------------------------------------------------------------- #
def run_ragas_evaluation(samples: list[dict[str, Any]]) -> dict[str, Any]:
    if not samples:
        return {"status": "not_run", "reason": "empty_sample_set", "metrics": {}}

    if ragas_available():
        real = _try_real_ragas(samples)
        if real is not None:
            return real
        logger.info("Falling back to RAGAS heuristic proxy.")

    metrics = _heuristic_metrics(samples)
    return {
        "status": "ok",
        "mode": "ragas_heuristic_proxy",
        "metrics": metrics,
        "n_samples": len(samples),
        "reason": "no_api_key_or_ragas_unavailable",
    }
