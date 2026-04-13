from __future__ import annotations

import argparse
import os
import socket
import subprocess
import sys
import time
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Start local API and worker services")
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--timeout-seconds", type=int, default=30)
    return parser.parse_args()


def _wait_for_port(port: int, timeout_seconds: int) -> bool:
    start = time.time()
    while time.time() - start < timeout_seconds:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(1.0)
            if sock.connect_ex(("127.0.0.1", port)) == 0:
                return True
        time.sleep(1)
    return False


def _stop_previous_process(pid_file: Path) -> None:
    if not pid_file.exists():
        return
    try:
        pid = int(pid_file.read_text(encoding="utf-8").strip())
    except Exception:
        pid_file.unlink(missing_ok=True)
        return
    try:
        os.kill(pid, 9)
    except Exception:
        pass
    pid_file.unlink(missing_ok=True)


def _open_log_file(path: Path):
    try:
        return path.open("w", encoding="utf-8"), path
    except PermissionError:
        fallback = path.with_name(f"{path.stem}_{int(time.time())}{path.suffix}")
        return fallback.open("w", encoding="utf-8"), fallback


def main() -> int:
    args = parse_args()
    root = Path(__file__).resolve().parents[1]
    logs = root / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    _stop_previous_process(logs / "api_local.pid")
    _stop_previous_process(logs / "worker_local.pid")
    time.sleep(1)

    python_exe = Path(sys.executable)
    api_stdout, api_stdout_path = _open_log_file(logs / "api_local.log")
    api_stderr, api_stderr_path = _open_log_file(logs / "api_local.err.log")
    worker_stdout, worker_stdout_path = _open_log_file(logs / "worker_local.log")
    worker_stderr, worker_stderr_path = _open_log_file(logs / "worker_local.err.log")

    env = os.environ.copy()
    existing_pythonpath = env.get("PYTHONPATH", "").strip()
    root_str = str(root)
    pythonpath_parts: list[str] = []
    venv_site_packages = root / ".venv" / "Lib" / "site-packages"
    if venv_site_packages.exists():
        pythonpath_parts.append(str(venv_site_packages))
    pythonpath_parts.append(root_str)
    if existing_pythonpath:
        pythonpath_parts.append(existing_pythonpath)
    env["PYTHONPATH"] = os.pathsep.join(pythonpath_parts)

    api_proc = subprocess.Popen(
        [
            str(python_exe),
            "-m",
            "uvicorn",
            "app.api.main:app",
            "--host",
            "0.0.0.0",
            "--port",
            str(args.port),
        ],
        cwd=str(root),
        stdout=api_stdout,
        stderr=api_stderr,
        env=env,
    )
    worker_proc = subprocess.Popen(
        [str(python_exe), "-m", "worker.main"],
        cwd=str(root),
        stdout=worker_stdout,
        stderr=worker_stderr,
        env=env,
    )

    (logs / "api_local.pid").write_text(str(api_proc.pid), encoding="utf-8")
    (logs / "worker_local.pid").write_text(str(worker_proc.pid), encoding="utf-8")
    (logs / "api_local.latest").write_text(str(api_stdout_path.name), encoding="utf-8")
    (logs / "worker_local.latest").write_text(str(worker_stdout_path.name), encoding="utf-8")
    (logs / "api_local.err.latest").write_text(str(api_stderr_path.name), encoding="utf-8")
    (logs / "worker_local.err.latest").write_text(str(worker_stderr_path.name), encoding="utf-8")

    ready = _wait_for_port(args.port, args.timeout_seconds)
    if not ready:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
