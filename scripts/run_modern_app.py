from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

import requests


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Start modern BIST Agentic RAG app (API + Next.js UI)")
    parser.add_argument("--api-port", type=int, default=18002)
    parser.add_argument("--ui-port", type=int, default=3000)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--skip-ui", action="store_true")
    parser.add_argument("--timeout-seconds", type=int, default=90)
    return parser.parse_args()


def wait_http(url: str, timeout_seconds: int) -> bool:
    started = time.time()
    while time.time() - started < timeout_seconds:
        try:
            response = requests.get(url, timeout=2)
            if response.status_code < 500:
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

    logs = root / "logs"
    logs.mkdir(parents=True, exist_ok=True)

    stop_script = root / "scripts" / "stop_local_services.py"
    start_script = root / "scripts" / "start_local_services.py"
    subprocess.run([str(python_exe), str(stop_script), "--logs-dir", "logs"], cwd=str(root), check=False)
    subprocess.run(
        [str(python_exe), str(start_script), "--port", str(args.api_port), "--timeout-seconds", "45"],
        cwd=str(root),
        check=True,
    )

    api_base = f"http://127.0.0.1:{args.api_port}"
    if not wait_http(f"{api_base}/v1/health", timeout_seconds=45):
        raise SystemExit("API health check failed.")

    ui_proc: subprocess.Popen | None = None
    ui_base = f"http://127.0.0.1:{args.ui_port}"
    if not args.skip_ui:
        npm_cmd = "npm.cmd" if os.name == "nt" else "npm"
        env = os.environ.copy()
        env["NEXT_PUBLIC_API_BASE"] = api_base
        env["PORT"] = str(args.ui_port)
        frontend = root / "frontend"
        if not (frontend / "node_modules").exists():
            subprocess.run([npm_cmd, "install"], cwd=str(frontend), check=True)
        ui_proc = subprocess.Popen(
            [npm_cmd, "run", "dev", "--", "-p", str(args.ui_port)],
            cwd=str(frontend),
            env=env,
            stdout=(logs / "web_ui.log").open("w", encoding="utf-8"),
            stderr=(logs / "web_ui.err.log").open("w", encoding="utf-8"),
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
        )
        if not wait_http(ui_base, timeout_seconds=args.timeout_seconds):
            raise SystemExit("Web UI did not start in time.")

    if not args.no_browser:
        webbrowser.open(ui_base if ui_proc else api_base)

    print(f"API: {api_base}")
    if ui_proc:
        print(f"UI: {ui_base}")
    print("Press ENTER to stop services...")
    try:
        input()
    except KeyboardInterrupt:
        pass
    finally:
        if ui_proc:
            try:
                if os.name == "nt":
                    ui_proc.send_signal(signal.CTRL_BREAK_EVENT)  # type: ignore[attr-defined]
                else:
                    ui_proc.terminate()
            except Exception:
                pass
            try:
                ui_proc.wait(timeout=8)
            except Exception:
                ui_proc.kill()
        subprocess.run([str(python_exe), str(stop_script), "--logs-dir", "logs"], cwd=str(root), check=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
