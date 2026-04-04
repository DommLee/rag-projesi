from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
import sys

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.evaluation.dataset import load_eval_questions
from app.evaluation.fixtures import build_eval_fixture_chunks
from app.service import BISTAgentService


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Seed local evaluation corpus fixtures")
    parser.add_argument("--dataset-path", default="datasets/eval_questions.json")
    parser.add_argument("--only-if-empty", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    service = BISTAgentService()
    questions = load_eval_questions(args.dataset_path)
    tickers = sorted({q["ticker"].upper() for q in questions})

    if args.only_if_empty:
        probe_docs = service.retriever.retrieve(  # type: ignore[attr-defined]
            query=f"{tickers[0]} probe",
            ticker=tickers[0],
            source_types=None,
            as_of_date=datetime.now(UTC),
            top_k=1,
        )
        if probe_docs:
            print(json.dumps({"seeded": 0, "status": "skipped_non_empty_corpus"}, ensure_ascii=False))
            return

    chunks = build_eval_fixture_chunks(questions)
    inserted = service.vector_store.upsert(chunks)  # type: ignore[attr-defined]
    print(
        json.dumps(
            {
                "seeded": inserted,
                "tickers": len(tickers),
                "dataset_path": args.dataset_path,
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()

