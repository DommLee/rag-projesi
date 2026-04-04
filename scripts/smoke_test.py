from __future__ import annotations

import argparse
import json
import sys

import requests


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="API smoke test")
    parser.add_argument("--base-url", default="http://localhost:18000")
    parser.add_argument("--ticker", default="ASELS")
    return parser.parse_args()


def assert_ok(resp: requests.Response, label: str) -> None:
    if resp.status_code >= 300:
        raise RuntimeError(f"{label} failed: {resp.status_code} {resp.text}")


def main() -> None:
    args = parse_args()
    base_url = args.base_url.rstrip("/")

    health = requests.get(f"{base_url}/v1/health", timeout=10)
    assert_ok(health, "health")

    ready = requests.get(f"{base_url}/v1/ready", timeout=10)
    assert_ok(ready, "ready")

    query_resp = requests.post(
        f"{base_url}/v1/query",
        json={
            "ticker": args.ticker,
            "question": "Summarize latest official and news narrative with citations.",
            "language": "bilingual",
            "provider_pref": "mock",
        },
        timeout=45,
    )
    assert_ok(query_resp, "query")
    payload = query_resp.json()
    if "disclaimer" not in payload:
        raise RuntimeError("query response missing disclaimer field")
    if payload.get("disclaimer") != "This system does not provide investment advice.":
        raise RuntimeError("disclaimer text mismatch")
    if "citation_coverage_score" not in payload:
        raise RuntimeError("query response missing citation_coverage_score")
    if "provider_used" not in payload:
        raise RuntimeError("query response missing provider_used")

    print(json.dumps({"health": health.json(), "ready": ready.json(), "query": payload}, indent=2))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # noqa: BLE001
        print(str(exc))
        sys.exit(1)
