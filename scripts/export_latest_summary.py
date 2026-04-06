from __future__ import annotations

import argparse
import json
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export latest run summary from eval report")
    parser.add_argument("--eval-report", default="logs/eval_report.json")
    parser.add_argument("--output", default="docs/latest_run_summary.md")
    return parser.parse_args()


def _gate(value: float, threshold: float) -> str:
    return "PASS" if value >= threshold else "FAIL"


def main() -> int:
    args = parse_args()
    eval_path = Path(args.eval_report)
    out_path = Path(args.output)
    if not eval_path.exists():
        raise FileNotFoundError(f"Eval report not found: {eval_path}")

    report = json.loads(eval_path.read_text(encoding="utf-8"))
    citation_coverage = float(report.get("citation_coverage", 0.0))
    disclaimer_presence = float(report.get("disclaimer_presence", 0.0))
    contradiction_accuracy = float(report.get("contradiction_detection_accuracy", 0.0))
    effective_mode = report.get("evaluation_mode_effective", "unknown")
    real_provider_available = bool(report.get("real_provider_available", False))
    gate_results = report.get("gate_results", {})
    total_score = float(report.get("rubric_scores", {}).get("total_100", 0.0))
    notes = report.get("notes", [])

    lines = [
        "# Latest Run Summary",
        "",
        f"- Mode: `{report.get('mode', 'unknown')}`",
        f"- Effective Mode: `{effective_mode}`",
        f"- Provider: `{report.get('provider', 'unknown')}`",
        f"- Real Provider Available: `{real_provider_available}`",
        f"- Total Questions: `{report.get('total_questions', 0)}`",
        f"- Rubric Total: `{total_score}` / 100",
        "",
        "## Acceptance Gates",
        f"- Citation Coverage >= 0.95: **{_gate(citation_coverage, 0.95)}** (`{citation_coverage:.4f}`)",
        f"- Disclaimer Presence = 1.00: **{_gate(disclaimer_presence, 1.0)}** (`{disclaimer_presence:.4f}`)",
        f"- Contradiction Detection Accuracy >= 0.75: **{_gate(contradiction_accuracy, 0.75)}** (`{contradiction_accuracy:.4f}`)",
        "",
        "## Gate Results (Runtime)",
    ]
    for key, value in gate_results.items():
        lines.append(f"- {key}: **{'PASS' if value else 'FAIL'}**")

    lines.extend(
        [
            "",
        "## Notes",
        ]
    )
    for note in notes:
        lines.append(f"- {note}")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines), encoding="utf-8")
    print(str(out_path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
