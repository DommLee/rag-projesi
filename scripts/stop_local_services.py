from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Stop locally started API/worker processes")
    parser.add_argument("--logs-dir", default="logs")
    return parser.parse_args()


def _taskkill_pid(pid: int) -> bool:
    result = subprocess.run(
        ["taskkill", "/PID", str(pid), "/T", "/F"],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode == 0


def _stop_from_pid_file(pid_file: Path) -> dict:
    if not pid_file.exists():
        return {"pid_file": str(pid_file), "status": "missing"}
    try:
        pid = int(pid_file.read_text(encoding="utf-8").strip())
    except Exception:
        pid_file.unlink(missing_ok=True)
        return {"pid_file": str(pid_file), "status": "invalid_pid"}

    stopped = _taskkill_pid(pid)
    pid_file.unlink(missing_ok=True)
    return {
        "pid_file": str(pid_file),
        "pid": pid,
        "status": "stopped" if stopped else "not_running_or_failed",
    }


def main() -> int:
    args = parse_args()
    logs = Path(args.logs_dir)
    items = [
        _stop_from_pid_file(logs / "api_local.pid"),
        _stop_from_pid_file(logs / "worker_local.pid"),
    ]

    for marker in [
        logs / "api_local.latest",
        logs / "worker_local.latest",
        logs / "api_local.err.latest",
        logs / "worker_local.err.latest",
    ]:
        marker.unlink(missing_ok=True)

    print(json.dumps({"stops": items}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

