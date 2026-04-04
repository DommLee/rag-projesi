from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.evaluation.dataset import load_eval_questions
from app.schemas import EvalRequest
from app.service import BISTAgentService


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run evaluation suite")
    parser.add_argument("--mode", default="hybrid")
    parser.add_argument("--provider", default="auto")
    parser.add_argument("--sample-size", type=int, default=15)
    parser.add_argument("--dataset-path", default="datasets/eval_questions.json")
    parser.add_argument("--store-artifacts", action="store_true")
    parser.add_argument("--output-path", default="logs/eval_report.json")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    service = BISTAgentService()
    result = service.eval_run(
        EvalRequest(
            mode=args.mode,
            provider=args.provider,
            sample_size=args.sample_size,
            dataset_path=args.dataset_path,
            store_artifacts=args.store_artifacts,
            run_ragas=True,
            run_deepeval=True,
        )
    )
    Path(args.output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(args.output_path, "w", encoding="utf-8") as file_obj:
        json.dump(result.model_dump(), file_obj, ensure_ascii=False, indent=2)

    print(json.dumps(result.model_dump(), ensure_ascii=False, indent=2))
    print(f"Loaded questions: {len(load_eval_questions(args.dataset_path))}")


if __name__ == "__main__":
    main()
