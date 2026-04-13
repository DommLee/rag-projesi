"""Tests for the heuristic RAGAS / DeepEval proxies.

We don't test the real OpenAI-backed paths here (those need network and
API keys). What we lock in is:

1. Empty samples -> not_run with empty metrics dict
2. Non-empty samples -> proxy mode runs and emits all named metrics
3. Faithfulness moves up when answer/context overlap is higher
"""

from __future__ import annotations

from app.evaluation.deepeval_eval import run_deepeval_evaluation
from app.evaluation.ragas_eval import run_ragas_evaluation


_GOOD_SAMPLE = {
    "question": "ASELS son 6 ayda hangi KAP açıklamalarını yaptı?",
    "answer": (
        "ASELS son altı ayda yeni bir savunma ihalesi sözleşmesi ve yıllık finansal raporunu KAP'ta paylaştı."
    ),
    "contexts": [
        "ASELS savunma ihalesi sözleşmesi imzaladı, yeni proje açıklandı.",
        "ASELS yıllık finansal raporunu KAP'a yükledi.",
    ],
    "ground_truth": "Aselsan KAP açıklamaları arasında yeni savunma sözleşmesi ve finansal rapor bulunuyor.",
}

_NOISY_SAMPLE = {
    "question": "Ne haber var?",
    "answer": "Sistem cevap üretmedi.",
    "contexts": ["Tamamen alakasız bir kripto para haberi içeriği."],
    "ground_truth": "",
}


def test_ragas_returns_not_run_for_empty_samples() -> None:
    result = run_ragas_evaluation([])
    assert result["status"] == "not_run"
    assert result["metrics"] == {}


def test_ragas_proxy_emits_all_metric_names() -> None:
    result = run_ragas_evaluation([_GOOD_SAMPLE])
    assert result["status"] == "ok"
    assert result["mode"] in {"ragas_real", "ragas_heuristic_proxy"}
    metrics = result["metrics"]
    for key in ("faithfulness", "answer_relevancy", "context_precision", "context_recall"):
        assert key in metrics, f"missing RAGAS metric: {key}"
        assert 0.0 <= metrics[key] <= 1.0


def test_ragas_proxy_distinguishes_grounded_from_noisy_answers() -> None:
    grounded = run_ragas_evaluation([_GOOD_SAMPLE])
    noisy = run_ragas_evaluation([_NOISY_SAMPLE])
    assert grounded["metrics"]["faithfulness"] > noisy["metrics"]["faithfulness"]


def test_deepeval_proxy_emits_all_metric_names() -> None:
    result = run_deepeval_evaluation([_GOOD_SAMPLE])
    assert result["status"] == "ok"
    assert result["mode"] in {"deepeval_real", "deepeval_heuristic_proxy"}
    metrics = result["metrics"]
    for key in ("hallucination_rate", "answer_relevancy", "faithfulness"):
        assert key in metrics, f"missing DeepEval metric: {key}"
        assert 0.0 <= metrics[key] <= 1.0


def test_deepeval_hallucination_drops_when_answer_is_grounded() -> None:
    grounded = run_deepeval_evaluation([_GOOD_SAMPLE])
    noisy = run_deepeval_evaluation([_NOISY_SAMPLE])
    assert grounded["metrics"]["hallucination_rate"] < noisy["metrics"]["hallucination_rate"]
