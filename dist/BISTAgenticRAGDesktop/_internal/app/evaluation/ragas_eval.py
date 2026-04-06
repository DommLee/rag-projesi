from __future__ import annotations

import os
from typing import Any


def ragas_available() -> bool:
    return bool(os.environ.get("OPENAI_API_KEY"))


def run_ragas_evaluation(samples: list[dict[str, Any]]) -> dict[str, Any]:
    _ = samples
    if not ragas_available():
        return {"status": "not_run", "reason": "llm_judge_disabled_no_api_key", "metrics": {}}
    # v1.2 default is heuristic-only.
    return {"status": "not_run", "reason": "heuristic_only_mode", "metrics": {}}

