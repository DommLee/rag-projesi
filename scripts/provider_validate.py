from __future__ import annotations

import argparse
import json

import requests


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Provider validation client")
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--provider", default="")
    parser.add_argument("--overrides", default="")
    parser.add_argument("--prompt", default="Reply with OK.")
    parser.add_argument("--token", default="")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    base_url = args.base_url.rstrip("/")
    headers = {"Content-Type": "application/json"}
    if args.token:
        headers["X-API-Token"] = args.token

    overrides = None
    if args.overrides.strip():
        parsed = json.loads(args.overrides)
        if not isinstance(parsed, dict):
            raise SystemExit("--overrides must be a JSON object")
        overrides = {str(k): str(v) for k, v in parsed.items() if v is not None}

    payload = {
        "provider_pref": args.provider or None,
        "provider_overrides": overrides,
        "prompt": args.prompt,
    }
    response = requests.post(f"{base_url}/v1/provider/validate", headers=headers, json=payload, timeout=120)
    print(response.status_code)
    try:
        print(json.dumps(response.json(), ensure_ascii=False, indent=2))
    except Exception:  # noqa: BLE001
        print(response.text)


if __name__ == "__main__":
    main()
