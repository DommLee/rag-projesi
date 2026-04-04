from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
import sys

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.schemas import IngestRequest
from app.service import BISTAgentService


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Live ingestion runner")
    parser.add_argument("--ticker", required=True)
    parser.add_argument("--institution", default="unknown")
    parser.add_argument("--kap-urls", default="")
    parser.add_argument("--news-urls", default="")
    parser.add_argument("--report-urls", default="")
    parser.add_argument("--date-from", default="")
    parser.add_argument("--date-to", default="")
    parser.add_argument("--delta-mode", default="true")
    parser.add_argument("--max-docs", type=int, default=100)
    parser.add_argument("--force-reingest", action="store_true")
    return parser.parse_args()


def _split_urls(raw: str) -> list[str]:
    return [u.strip() for u in raw.split(",") if u.strip()]


def _dt(value: str):
    if not value:
        return None
    return datetime.fromisoformat(value).astimezone(UTC)


def main() -> None:
    args = parse_args()
    service = BISTAgentService()

    req_base = {
        "ticker": args.ticker,
        "institution": args.institution,
        "date_from": _dt(args.date_from),
        "date_to": _dt(args.date_to),
        "delta_mode": str(args.delta_mode).lower() == "true",
        "max_docs": args.max_docs,
        "force_reingest": args.force_reingest,
    }

    result = {"kap": {"inserted": 0}, "news": {"inserted": 0}, "report": {"inserted": 0}}

    kap_urls = _split_urls(args.kap_urls)
    if kap_urls:
        inserted = service.ingest_kap(IngestRequest(**req_base, source_urls=kap_urls))
        result["kap"] = {"inserted": inserted, "stats": service.last_ingest_stats}

    news_urls = _split_urls(args.news_urls)
    if news_urls:
        inserted = service.ingest_news(IngestRequest(**req_base, source_urls=news_urls))
        result["news"] = {"inserted": inserted, "stats": service.last_ingest_stats}

    report_urls = _split_urls(args.report_urls)
    if report_urls:
        inserted = service.ingest_report(IngestRequest(**req_base, source_urls=report_urls))
        result["report"] = {"inserted": inserted, "stats": service.last_ingest_stats}

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
