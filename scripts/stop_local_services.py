from __future__ import annotations

import argparse
import json
import socket
import subprocess
import time
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


def _wait_for_ports_to_close(ports: list[int], timeout_seconds: float = 8.0) -> dict[int, bool]:
    deadline = time.time() + timeout_seconds
    status = {port: False for port in ports}
    while time.time() < deadline:
        open_ports = []
        for port in ports:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.settimeout(0.5)
                if sock.connect_ex(("127.0.0.1", port)) == 0:
                    open_ports.append(port)
                else:
                    status[port] = True
        if not open_ports:
            return status
        time.sleep(0.5)
    return status


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

    port_closure = _wait_for_ports_to_close([18000, 18001, 18002, 8088])
    print(json.dumps({"stops": items, "port_closure": port_closure}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
