from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.evaluation.fixtures import build_eval_fixture_chunks
from app.schemas import QueryRequest
from app.service import BISTAgentService


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Rubric-aligned final demo flow")
    parser.add_argument("--ticker", default="ASELS")
    parser.add_argument(
        "--question",
        default="Are recent news articles consistent with official KAP disclosures?",
    )
    parser.add_argument("--provider", default="mock")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    service = BISTAgentService()
    ticker = args.ticker.upper()
    ts = datetime.now(UTC).strftime("%Y-%m-%d %H:%M")

    print("=" * 60)
    print(f"  BIST Agentic RAG - Demo Flow ({ts})")
    print("=" * 60)

    print(f"\n[1/7] Select ticker: {ticker}")
    print("[2/7] Retrieve KAP disclosures")
    print("[3/7] Retrieve news")
    print("[4/7] Parse brokerage reports")

    existing = service.retriever.retrieve(
        query=f"{ticker} official and news narrative",
        ticker=ticker,
        source_types=None,
        as_of_date=None,
        top_k=3,
    )
    if not existing:
        seeded = build_eval_fixture_chunks([{"ticker": ticker, "expected_consistency": "inconclusive"}])
        inserted = service.vector_store.upsert(seeded)
        print(f"[INFO] Seeded fixture chunks: {inserted}")

    print("[5/7] Agent compares narratives")
    response = service.query(
        QueryRequest(
            ticker=ticker,
            question=args.question,
            language="bilingual",
            provider_pref=args.provider,
        )
    )

    print("[6/7] Generates cited answer")
    print("[7/7] Shows disclaimer")
    print(json.dumps(response.model_dump(), ensure_ascii=False, indent=2, default=str))

    docs_dir = ROOT_DIR / "docs"
    docs_dir.mkdir(parents=True, exist_ok=True)
    summary_path = docs_dir / "latest_run_summary.md"
    summary_lines = [
        "# Demo Flow Summary",
        "",
        f"- Timestamp: `{ts}`",
        f"- Ticker: `{ticker}`",
        f"- Provider: `{args.provider}`",
        f"- Consistency: `{response.consistency_assessment}`",
        f"- Citation Count: `{len(response.citations)}`",
        f"- Coverage: `{response.citation_coverage_score:.4f}`",
        f"- Disclaimer: `{'present' if 'investment advice' in response.disclaimer.lower() else 'missing'}`",
    ]
    summary_path.write_text("\n".join(summary_lines), encoding="utf-8")
    print(f"[INFO] Summary written to {summary_path}")


if __name__ == "__main__":
    main()

