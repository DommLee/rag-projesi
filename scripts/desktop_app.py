from __future__ import annotations

import json
import os
import subprocess
import threading
import webbrowser
from pathlib import Path

import requests
import tkinter as tk
from tkinter import messagebox, ttk


class DesktopApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("BIST Agentic RAG Desktop")
        self.root.geometry("1100x760")
        self.project_root = Path(__file__).resolve().parents[1]
        self.api_port_var = tk.StringVar(value=self._read_runtime_port() or "18002")
        self.status_var = tk.StringVar(value="Service not started")
        self.provider_var = tk.StringVar(value="mock")
        self.eval_mode_var = tk.StringVar(value="hybrid")
        self.eval_provider_var = tk.StringVar(value="auto")
        self.sample_size_var = tk.StringVar(value="15")
        self.ticker_var = tk.StringVar(value="ASELS")
        self.question_var = tk.StringVar(value="Do recent news articles align with official KAP disclosures?")

        self._build_ui()
        self._refresh_health()

    def _build_ui(self) -> None:
        container = ttk.Frame(self.root, padding=12)
        container.pack(fill=tk.BOTH, expand=True)

        top = ttk.LabelFrame(container, text="Service Control", padding=10)
        top.pack(fill=tk.X, padx=4, pady=4)

        ttk.Label(top, text="Port").grid(row=0, column=0, sticky="w")
        ttk.Entry(top, textvariable=self.api_port_var, width=10).grid(row=0, column=1, padx=6)

        ttk.Button(top, text="Start Service", command=self.start_service).grid(row=0, column=2, padx=4)
        ttk.Button(top, text="Stop Service", command=self.stop_service).grid(row=0, column=3, padx=4)
        ttk.Button(top, text="Health Check", command=self._refresh_health).grid(row=0, column=4, padx=4)
        ttk.Button(top, text="Open Dashboard", command=self.open_dashboard).grid(row=0, column=5, padx=4)

        ttk.Label(top, textvariable=self.status_var, foreground="#0f5132").grid(row=1, column=0, columnspan=6, sticky="w", pady=(8, 0))

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
        ttk.Combobox(eval_box, textvariable=self.eval_mode_var, values=["hybrid", "mock", "real"], state="readonly", width=12).grid(row=0, column=1, padx=6)

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
        webbrowser.open(f"{self._base_url()}/")

    def run_query(self) -> None:
        def task() -> object:
            payload = {
                "ticker": self.ticker_var.get().strip().upper(),
                "question": self.question_text.get("1.0", tk.END).strip(),
                "language": "bilingual",
                "provider_pref": self.provider_var.get().strip() or None,
            }
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
    root = tk.Tk()
    DesktopApp(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
