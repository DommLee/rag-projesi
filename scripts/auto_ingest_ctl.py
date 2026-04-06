from __future__ import annotations

import argparse
import json
from pathlib import Path

import requests


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Auto ingest control client")
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--action", required=True, choices=["status", "start", "stop", "run-once", "get-config", "set-config"])
    parser.add_argument("--config-path", default="")
    parser.add_argument("--token", default="")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    base_url = args.base_url.rstrip("/")
    headers = {"Content-Type": "application/json"}
    if args.token:
        headers["X-API-Token"] = args.token

    if args.action == "status":
        response = requests.get(f"{base_url}/v1/auto-ingest/status", headers=headers, timeout=30)
    elif args.action == "start":
        response = requests.post(f"{base_url}/v1/auto-ingest/start", headers=headers, timeout=30)
    elif args.action == "stop":
        response = requests.post(f"{base_url}/v1/auto-ingest/stop", headers=headers, timeout=30)
    elif args.action == "run-once":
        response = requests.post(f"{base_url}/v1/auto-ingest/run-once", headers=headers, timeout=300)
    elif args.action == "get-config":
        response = requests.get(f"{base_url}/v1/auto-ingest/config", headers=headers, timeout=30)
    else:
        if not args.config_path:
            raise SystemExit("--config-path is required for set-config")
        config_path = Path(args.config_path)
        if not config_path.exists():
            raise SystemExit(f"Config file not found: {config_path}")
        payload = json.loads(config_path.read_text(encoding="utf-8-sig"))
        response = requests.post(
            f"{base_url}/v1/auto-ingest/config",
            headers=headers,
            json=payload,
            timeout=30,
        )

    print(response.status_code)
    try:
        print(json.dumps(response.json(), ensure_ascii=False, indent=2))
    except Exception:  # noqa: BLE001
        print(response.text)


if __name__ == "__main__":
    main()
