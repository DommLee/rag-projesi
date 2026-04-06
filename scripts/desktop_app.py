from __future__ import annotations

import argparse
import json
import multiprocessing
import os
import socket
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path

import requests
import tkinter as tk
from tkinter import messagebox, ttk


def _bootstrap_import_path() -> None:
    candidates: list[Path] = []
    if getattr(sys, "frozen", False):
        exe_root = Path(sys.executable).resolve().parent
        candidates.extend([exe_root, exe_root.parent])
    else:
        candidates.append(Path(__file__).resolve().parents[1])

    for candidate in candidates:
        if (candidate / "app").exists():
            path = str(candidate)
            if path not in sys.path:
                sys.path.insert(0, path)
            break


_bootstrap_import_path()


def resource_path(relative_path: str) -> str:
    """Get absolute path to resource, works for dev and PyInstaller."""
    try:
        base_path = sys._MEIPASS  # type: ignore[attr-defined]
    except AttributeError:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)


class DesktopApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("BIST Agentic RAG Desktop")
        self.root.geometry("1100x760")
        self.project_root = self._resolve_project_root()
        self.api_port_var = tk.StringVar(value=self._read_runtime_port() or "18002")
        self.status_var = tk.StringVar(value="Service not started")
        self.provider_var = tk.StringVar(value="mock")
        self.eval_mode_var = tk.StringVar(value="heuristic")
        self.eval_provider_var = tk.StringVar(value="auto")
        self.sample_size_var = tk.StringVar(value="15")
        self.ticker_var = tk.StringVar(value="ASELS")
        self.question_var = tk.StringVar(value="Do recent news articles align with official KAP disclosures?")
        self.api_token_var = tk.StringVar(value=os.environ.get("API_AUTH_TOKEN", ""))
        self.autostart_var = tk.BooleanVar(
            value=os.environ.get("DESKTOP_AUTOSTART", "1").strip().lower() not in {"0", "false", "no"}
        )

        self._build_ui()
        self._refresh_health()
        self.root.after(250, self._auto_start_if_needed)

    @staticmethod
    def _resolve_project_root() -> Path:
        if getattr(sys, "frozen", False):
            exe_root = Path(sys.executable).resolve().parent
            if (exe_root / "30_run_api.bat").exists():
                return exe_root
            if (exe_root.parent / "30_run_api.bat").exists():
                return exe_root.parent
            return exe_root
        return Path(__file__).resolve().parents[1]

    def _build_ui(self) -> None:
        container = ttk.Frame(self.root, padding=12)
        container.pack(fill=tk.BOTH, expand=True)

        top = ttk.LabelFrame(container, text="Service Control", padding=10)
        top.pack(fill=tk.X, padx=4, pady=4)

        ttk.Label(top, text="Port").grid(row=0, column=0, sticky="w")
        ttk.Entry(top, textvariable=self.api_port_var, width=10).grid(row=0, column=1, padx=6)
        ttk.Label(top, text="API Token").grid(row=0, column=6, sticky="w")
        ttk.Entry(top, textvariable=self.api_token_var, width=24, show="*").grid(row=0, column=7, padx=6)
        ttk.Checkbutton(top, text="Auto Start", variable=self.autostart_var).grid(row=0, column=8, padx=6, sticky="w")

        ttk.Button(top, text="Start Service", command=self.start_service).grid(row=0, column=2, padx=4)
        ttk.Button(top, text="Stop Service", command=self.stop_service).grid(row=0, column=3, padx=4)
        ttk.Button(top, text="Health Check", command=self._refresh_health).grid(row=0, column=4, padx=4)
        ttk.Button(top, text="Open Dashboard", command=self.open_dashboard).grid(row=0, column=5, padx=4)

        ttk.Label(top, textvariable=self.status_var, foreground="#0f5132").grid(row=1, column=0, columnspan=9, sticky="w", pady=(8, 0))

        query_box = ttk.LabelFrame(container, text="Query", padding=10)
        query_box.pack(fill=tk.X, padx=4, pady=4)

        ttk.Label(query_box, text="Ticker").grid(row=0, column=0, sticky="w")
        ttk.Entry(query_box, textvariable=self.ticker_var, width=12).grid(row=0, column=1, padx=6, sticky="w")

        ttk.Label(query_box, text="Provider").grid(row=0, column=2, sticky="w")
        provider_combo = ttk.Combobox(
            query_box,
            textvariable=self.provider_var,
            values=["mock", "ollama", "openai", "together", ""],
            width=12,
            state="readonly",
        )
        provider_combo.grid(row=0, column=3, padx=6, sticky="w")

        ttk.Label(query_box, text="Question").grid(row=1, column=0, sticky="w", pady=(8, 0))
        self.question_text = tk.Text(query_box, height=4, width=110)
        self.question_text.insert("1.0", self.question_var.get())
        self.question_text.grid(row=2, column=0, columnspan=6, pady=6)

        ttk.Button(query_box, text="Run Query", command=self.run_query).grid(row=3, column=0, padx=4, pady=4, sticky="w")
        ttk.Button(query_box, text="Run Query Insight", command=self.run_query_insight).grid(row=3, column=1, padx=4, pady=4, sticky="w")

        eval_box = ttk.LabelFrame(container, text="Evaluation", padding=10)
        eval_box.pack(fill=tk.X, padx=4, pady=4)

        ttk.Label(eval_box, text="Mode").grid(row=0, column=0, sticky="w")
        ttk.Combobox(eval_box, textvariable=self.eval_mode_var, values=["heuristic", "hybrid", "mock", "real"], state="readonly", width=12).grid(row=0, column=1, padx=6)

        ttk.Label(eval_box, text="Provider").grid(row=0, column=2, sticky="w")
        ttk.Combobox(eval_box, textvariable=self.eval_provider_var, values=["auto", "mock", "ollama", "openai", "together"], state="readonly", width=12).grid(row=0, column=3, padx=6)

        ttk.Label(eval_box, text="Sample").grid(row=0, column=4, sticky="w")
        ttk.Entry(eval_box, textvariable=self.sample_size_var, width=8).grid(row=0, column=5, padx=6)

        ttk.Button(eval_box, text="Run Eval", command=self.run_eval).grid(row=0, column=6, padx=4)
        ttk.Button(eval_box, text="Open Latest Summary", command=self.open_latest_summary).grid(row=0, column=7, padx=4)

        out_box = ttk.LabelFrame(container, text="Output", padding=10)
        out_box.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)
        self.output = tk.Text(out_box, wrap=tk.WORD)
        self.output.pack(fill=tk.BOTH, expand=True)

        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    def _read_runtime_port(self) -> str:
        port_file = self.project_root / "logs" / ".runtime_api_port"
        if port_file.exists():
            return port_file.read_text(encoding="utf-8").strip()
        return ""

    def _base_url(self) -> str:
        return f"http://127.0.0.1:{self.api_port_var.get().strip()}"

    def _auth_headers(self) -> dict[str, str]:
        token = self.api_token_var.get().strip()
        return {"X-API-Token": token} if token else {}

    @staticmethod
    def _port_in_use(port: int) -> bool:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(0.5)
            return sock.connect_ex(("127.0.0.1", port)) == 0

    def _pick_service_port(self) -> int:
        candidates: list[int] = []
        try:
            preferred = int(self.api_port_var.get().strip())
            candidates.append(preferred)
        except Exception:
            pass
        candidates.extend([18000, 18001, 18002, 8088])
        seen: set[int] = set()
        ordered = [p for p in candidates if not (p in seen or seen.add(p))]
        for port in ordered:
            if not self._port_in_use(port):
                return port
        raise RuntimeError("No free port available in fallback matrix (18000,18001,18002,8088).")

    @staticmethod
    def _wait_for_port(port: int, timeout_seconds: int = 30) -> bool:
        start = time.time()
        while time.time() - start < timeout_seconds:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.settimeout(0.8)
                if sock.connect_ex(("127.0.0.1", port)) == 0:
                    return True
            time.sleep(0.6)
        return False

    def _logs_dir(self) -> Path:
        logs = self.project_root / "logs"
        logs.mkdir(parents=True, exist_ok=True)
        return logs

    @staticmethod
    def _open_log(path: Path):
        try:
            return path.open("w", encoding="utf-8")
        except PermissionError:
            fallback = path.with_name(f"{path.stem}_{int(time.time())}{path.suffix}")
            return fallback.open("w", encoding="utf-8")

    def _stop_embedded_services(self) -> str:
        logs = self._logs_dir()
        stopped: list[dict[str, object]] = []
        for pid_name in ("api_local.pid", "worker_local.pid"):
            pid_file = logs / pid_name
            if not pid_file.exists():
                stopped.append({"pid_file": pid_name, "status": "missing"})
                continue
            try:
                pid = int(pid_file.read_text(encoding="utf-8").strip())
            except Exception:
                pid_file.unlink(missing_ok=True)
                stopped.append({"pid_file": pid_name, "status": "invalid_pid"})
                continue
            proc = subprocess.run(
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                capture_output=True,
                text=True,
                check=False,
            )
            pid_file.unlink(missing_ok=True)
            stopped.append(
                {
                    "pid_file": pid_name,
                    "pid": pid,
                    "status": "stopped" if proc.returncode == 0 else "not_running_or_failed",
                }
            )

        for marker in ("api_local.latest", "worker_local.latest", "api_local.err.latest", "worker_local.err.latest"):
            (logs / marker).unlink(missing_ok=True)

        return json.dumps({"stops": stopped}, ensure_ascii=False)

    def _start_embedded_services(self) -> str:
        logs = self._logs_dir()
        self._stop_embedded_services()

        port = self._pick_service_port()
        self.api_port_var.set(str(port))
        (logs / ".runtime_api_port").write_text(str(port), encoding="utf-8")

        api_out = self._open_log(logs / "api_local.log")
        api_err = self._open_log(logs / "api_local.err.log")
        worker_out = self._open_log(logs / "worker_local.log")
        worker_err = self._open_log(logs / "worker_local.err.log")

        api_proc = subprocess.Popen(
            [sys.executable, "--run-api", "--port", str(port)],
            cwd=str(self.project_root),
            stdout=api_out,
            stderr=api_err,
        )
        worker_proc = subprocess.Popen(
            [sys.executable, "--run-worker"],
            cwd=str(self.project_root),
            stdout=worker_out,
            stderr=worker_err,
        )

        (logs / "api_local.pid").write_text(str(api_proc.pid), encoding="utf-8")
        (logs / "worker_local.pid").write_text(str(worker_proc.pid), encoding="utf-8")
        (logs / "api_local.latest").write_text("api_local.log", encoding="utf-8")
        (logs / "worker_local.latest").write_text("worker_local.log", encoding="utf-8")
        (logs / "api_local.err.latest").write_text("api_local.err.log", encoding="utf-8")
        (logs / "worker_local.err.latest").write_text("worker_local.err.log", encoding="utf-8")

        if not self._wait_for_port(port, timeout_seconds=35):
            raise RuntimeError("Embedded API did not start in time. Check logs/api_local.err.log")
        self._refresh_health()
        return f"Embedded services started on http://127.0.0.1:{port}"

    def _is_service_healthy(self, timeout: float = 2.0) -> bool:
        try:
            response = requests.get(f"{self._base_url()}/v1/health", timeout=timeout)
            return response.status_code == 200
        except Exception:
            return False

    def _auto_start_if_needed(self) -> None:
        if not self.autostart_var.get():
            return
        if self._is_service_healthy(timeout=1.5):
            self._refresh_health()
            return
        self.status_var.set("Service auto-starting...")
        self.start_service()

    def _append_output(self, title: str, payload: object) -> None:
        self.output.insert(tk.END, f"\n\n=== {title} ===\n")
        if isinstance(payload, str):
            self.output.insert(tk.END, payload)
        else:
            self.output.insert(tk.END, json.dumps(payload, ensure_ascii=False, indent=2))
        self.output.see(tk.END)

    def _run_background(self, func, success_title: str) -> None:
        def runner() -> None:
            try:
                result = func()
                self.root.after(0, lambda: self._append_output(success_title, result))
            except Exception as exc:  # noqa: BLE001
                self.root.after(0, lambda: self._append_output("ERROR", str(exc)))

        threading.Thread(target=runner, daemon=True).start()

    def start_service(self) -> None:
        def task() -> str:
            if self._is_service_healthy(timeout=1.5):
                self._refresh_health()
                return "Service already running."
            if getattr(sys, "frozen", False):
                return self._start_embedded_services()
            env_overrides = {
                "ALLOW_LOCAL_FALLBACK": "1",
                "SKIP_OLLAMA_PULL": "1",
                "API_HOST_PORT": self.api_port_var.get().strip(),
            }
            merged_env = os.environ.copy()
            merged_env.update(env_overrides)
            cmd = ["cmd", "/c", "30_run_api.bat"]
            process = subprocess.run(
                cmd,
                cwd=str(self.project_root),
                capture_output=True,
                text=True,
                env=merged_env,
                check=False,
            )
            output = "\n".join([part for part in [process.stdout.strip(), process.stderr.strip()] if part]).strip()
            if process.returncode != 0:
                raise RuntimeError(output or "30_run_api.bat failed")
            runtime = self._read_runtime_port()
            if runtime:
                self.api_port_var.set(runtime)
            self._refresh_health()
            return output or "Service started."

        self._run_background(task, "START SERVICE")

    def stop_service(self) -> None:
        def task() -> str:
            if getattr(sys, "frozen", False):
                output = self._stop_embedded_services()
                self.status_var.set("Service stopped")
                return output
            process = subprocess.run(
                ["cmd", "/c", "101_stop_app.bat"],
                cwd=str(self.project_root),
                capture_output=True,
                text=True,
                check=False,
            )
            output = "\n".join([part for part in [process.stdout.strip(), process.stderr.strip()] if part]).strip()
            self.status_var.set("Service stopped")
            if process.returncode != 0:
                raise RuntimeError(output or "101_stop_app.bat failed")
            return output or "Service stopped."

        self._run_background(task, "STOP SERVICE")

    def _refresh_health(self) -> None:
        try:
            response = requests.get(f"{self._base_url()}/v1/health", timeout=2)
            if response.status_code == 200:
                payload = response.json()
                self.status_var.set(f"Healthy: {payload.get('app', 'BIST Agentic RAG')} at {self._base_url()}")
            else:
                self.status_var.set(f"Health check failed ({response.status_code})")
        except Exception:
            self.status_var.set(f"Service not reachable at {self._base_url()}")

    def open_dashboard(self) -> None:
        preferred = os.environ.get("WEB_UI_URL", "http://127.0.0.1:3000").strip()
        try:
            response = requests.get(preferred, timeout=1.5)
            if response.status_code < 500:
                webbrowser.open(preferred)
                return
        except Exception:
            pass
        webbrowser.open(f"{self._base_url()}/")

    def run_query(self) -> None:
        def task() -> object:
            payload = {
                "ticker": self.ticker_var.get().strip().upper(),
                "question": self.question_text.get("1.0", tk.END).strip(),
                "language": "bilingual",
                "provider_pref": self.provider_var.get().strip() or None,
            }
            headers = self._auth_headers()
            if headers:
                response = requests.post(
                    f"{self._base_url()}/v1/query",
                    json=payload,
                    headers=headers,
                    timeout=60,
                )
            else:
                response = requests.post(f"{self._base_url()}/v1/query", json=payload, timeout=60)
            response.raise_for_status()
            return response.json()

        self._run_background(task, "QUERY")

    def run_query_insight(self) -> None:
        def task() -> object:
            payload = {
                "ticker": self.ticker_var.get().strip().upper(),
                "question": self.question_text.get("1.0", tk.END).strip(),
                "language": "bilingual",
                "provider_pref": self.provider_var.get().strip() or None,
            }
            headers = self._auth_headers()
            if headers:
                response = requests.post(
                    f"{self._base_url()}/v1/query/insight",
                    json=payload,
                    headers=headers,
                    timeout=60,
                )
            else:
                response = requests.post(f"{self._base_url()}/v1/query/insight", json=payload, timeout=60)
            response.raise_for_status()
            return response.json()

        self._run_background(task, "QUERY INSIGHT")

    def run_eval(self) -> None:
        def task() -> object:
            payload = {
                "mode": self.eval_mode_var.get().strip(),
                "provider": self.eval_provider_var.get().strip(),
                "sample_size": int(self.sample_size_var.get().strip() or "15"),
                "dataset_path": "datasets/eval_questions.json",
                "store_artifacts": True,
                "run_ragas": True,
                "run_deepeval": True,
            }
            headers = self._auth_headers()
            if headers:
                response = requests.post(
                    f"{self._base_url()}/v1/eval/run",
                    json=payload,
                    headers=headers,
                    timeout=180,
                )
            else:
                response = requests.post(f"{self._base_url()}/v1/eval/run", json=payload, timeout=180)
            response.raise_for_status()
            return response.json()

        self._run_background(task, "EVAL")

    def open_latest_summary(self) -> None:
        summary = self.project_root / "docs" / "latest_run_summary.md"
        if summary.exists():
            webbrowser.open(summary.as_uri())
        else:
            messagebox.showwarning("Summary Missing", "docs/latest_run_summary.md not found.")

    def on_close(self) -> None:
        try:
            if getattr(sys, "frozen", False):
                self._stop_embedded_services()
            else:
                subprocess.run(
                    ["cmd", "/c", "101_stop_app.bat"],
                    cwd=str(self.project_root),
                    capture_output=True,
                    text=True,
                    check=False,
                )
        finally:
            self.root.destroy()


def main() -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--run-api", action="store_true")
    parser.add_argument("--run-worker", action="store_true")
    parser.add_argument("--port", type=int, default=18000)
    args, _ = parser.parse_known_args()

    if args.run_api:
        from app.api.main import app as api_app
        import uvicorn

        uvicorn.run(api_app, host="0.0.0.0", port=args.port, log_level="info")
        return 0

    if args.run_worker:
        from worker.main import run_worker_loop

        run_worker_loop()
        return 0

    multiprocessing.freeze_support()
    root = tk.Tk()
    DesktopApp(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    multiprocessing.freeze_support()
    raise SystemExit(main())
