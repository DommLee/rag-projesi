from __future__ import annotations

import argparse
import socket
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

import requests


DEFAULT_PORT_CANDIDATES = [18000, 18001, 18002, 8088]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run BIST Agentic RAG as a local application")
    parser.add_argument("--port", type=int, default=0, help="Preferred API port. If 0, first free candidate is chosen.")
    parser.add_argument("--seed-eval-if-empty", action="store_true", help="Seed local eval fixture corpus when empty.")
    parser.add_argument("--no-browser", action="store_true", help="Do not open browser automatically.")
    parser.add_argument(
        "--auto-stop-seconds",
        type=int,
        default=0,
        help="Auto stop after N seconds. Use 0 for interactive mode.",
    )
    return parser.parse_args()


def is_port_in_use(port: int, host: str = "127.0.0.1") -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.7)
        return sock.connect_ex((host, port)) == 0


def pick_port(candidates: list[int], is_in_use=is_port_in_use) -> int:
    for candidate in candidates:
        if not is_in_use(candidate):
            return candidate
    raise RuntimeError("No free port available from candidate list.")


def build_base_url(port: int) -> str:
    return f"http://127.0.0.1:{port}"


def run_script(python_exe: Path, script_path: Path, extra_args: list[str], cwd: Path, check: bool = True) -> subprocess.CompletedProcess:
    cmd = [str(python_exe), str(script_path), *extra_args]
    proc = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True, check=False)
    if check and proc.returncode != 0:
        message = "\n".join([part for part in [proc.stdout.strip(), proc.stderr.strip()] if part]).strip()
        raise RuntimeError(f"{script_path.name} failed: {message}")
    return proc


def wait_for_health(base_url: str, timeout_seconds: int = 40) -> bool:
    started = time.time()
    while time.time() - started < timeout_seconds:
        try:
            response = requests.get(f"{base_url}/v1/health", timeout=2)
            if response.status_code == 200:
                return True
        except Exception:
            pass
        time.sleep(1)
    return False


def main() -> int:
    args = parse_args()
    root = Path(__file__).resolve().parents[1]
    python_exe = root / ".venv" / "Scripts" / "python.exe"
    if not python_exe.exists():
        python_exe = Path(sys.executable)

    port = args.port if args.port > 0 else pick_port(DEFAULT_PORT_CANDIDATES)
    base_url = build_base_url(port)

    print(f"[run_application] Starting local app on {base_url}")
    stop_script = root / "scripts" / "stop_local_services.py"
    start_script = root / "scripts" / "start_local_services.py"
    seed_script = root / "scripts" / "seed_eval_corpus.py"

    # Best-effort cleanup before startup.
    run_script(python_exe, stop_script, ["--logs-dir", "logs"], cwd=root, check=False)
    run_script(python_exe, start_script, ["--port", str(port), "--timeout-seconds", "45"], cwd=root, check=True)

    if not wait_for_health(base_url, timeout_seconds=45):
        run_script(python_exe, stop_script, ["--logs-dir", "logs"], cwd=root, check=False)
        raise RuntimeError("Application health check failed after startup.")

    if args.seed_eval_if_empty:
        seed = run_script(
            python_exe,
            seed_script,
            ["--dataset-path", "datasets/eval_questions.json", "--only-if-empty"],
            cwd=root,
            check=False,
        )
        output = "\n".join([part for part in [seed.stdout.strip(), seed.stderr.strip()] if part]).strip()
        if output:
            print(f"[run_application] {output}")

    if not args.no_browser:
        webbrowser.open(base_url)

    try:
        if args.auto_stop_seconds > 0:
            print(f"[run_application] Auto stop enabled: {args.auto_stop_seconds}s")
            time.sleep(args.auto_stop_seconds)
        else:
            print("[run_application] Press ENTER to stop application.")
            input()
    except KeyboardInterrupt:
        print("[run_application] Keyboard interrupt received, stopping.")
    finally:
        run_script(python_exe, stop_script, ["--logs-dir", "logs"], cwd=root, check=False)
        print("[run_application] Application stopped.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

