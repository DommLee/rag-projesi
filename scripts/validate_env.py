from __future__ import annotations

import argparse
import os
import sys


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate runtime environment variables")
    parser.add_argument("--mode", choices=["dev", "heuristic", "real"], default="heuristic")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    required = []
    optional = [
        "TOGETHER_API_KEY",
        "OPENAI_API_KEY",
        "VOYAGE_API_KEY",
        "NOMIC_API_KEY",
    ]

    if args.mode == "real":
        required.append("OPENAI_API_KEY")

    missing = [name for name in required if not os.environ.get(name)]

    print(f"[validate_env] mode={args.mode}")
    if missing:
        print(f"[validate_env] missing required env vars: {', '.join(missing)}")
        return 1

    present_optional = [name for name in optional if os.environ.get(name)]
    print(f"[validate_env] optional keys present: {len(present_optional)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

