from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.evaluation.fixtures import build_eval_fixture_chunks
from app.schemas import QueryRequest
from app.service import BISTAgentService


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Final demo flow")
    parser.add_argument("--ticker", required=True)
    parser.add_argument(
        "--question",
        default="Are recent news articles consistent with official KAP disclosures?",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    service = BISTAgentService()
    existing = service.retriever.retrieve(  # type: ignore[attr-defined]
        query=f"{args.ticker} official and news narrative",
        ticker=args.ticker,
        source_types=None,
        as_of_date=None,
        top_k=3,
    )
    if not existing:
        seeded = build_eval_fixture_chunks(
            [{"ticker": args.ticker.upper(), "expected_consistency": "inconclusive"}]
        )
        inserted = service.vector_store.upsert(seeded)  # type: ignore[attr-defined]
        print(f"[demo_flow] Seeded {inserted} local fixture chunks for {args.ticker}.")

    print("1) Select ticker:", args.ticker)
    print("2) Retrieve KAP disclosures")
    print("3) Retrieve news")
    print("4) Parse brokerage reports")
    print("5) Agent compares narratives")
    response = service.query(
        QueryRequest(
            ticker=args.ticker,
            question=args.question,
            language="bilingual",
            provider_pref="mock",
        )
    )
    print("6) Generates cited answer")
    print("7) Shows disclaimer")
    print(json.dumps(response.model_dump(), ensure_ascii=False, indent=2, default=str))
    if len(response.citations) < 3:
        print("[demo_flow] WARN: citation count is below 3 for this run.")


if __name__ == "__main__":
    main()
