from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
from datetime import UTC, datetime
from pathlib import Path


LOG_DIR_PATTERN = re.compile(r"^\d{8}_\d{4}$")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build GitHub-ready release bundle")
    parser.add_argument("--run-log-dir", default="", help="Specific logs run directory, e.g. logs/20260404_2201")
    parser.add_argument("--output-root", default="releases")
    return parser.parse_args()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def latest_run_log_dir(logs_root: Path) -> Path | None:
    candidates = []
    if not logs_root.exists():
        return None
    for child in logs_root.iterdir():
        if child.is_dir() and LOG_DIR_PATTERN.match(child.name):
            candidates.append(child)
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_mtime)


def copy_if_exists(src: Path, dst: Path, copied: list[str]) -> None:
    if not src.exists():
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    copied.append(str(dst))


def copy_tree_if_exists(src: Path, dst: Path, copied: list[str]) -> None:
    if not src.exists():
        return
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)
    for p in dst.rglob("*"):
        if p.is_file():
            copied.append(str(p))


def extract_gate_metrics(eval_report: dict) -> dict:
    citation = float(eval_report.get("citation_coverage", 0.0))
    disclaimer = float(eval_report.get("disclaimer_presence", 0.0))
    contradiction = float(eval_report.get("contradiction_detection_accuracy", 0.0))
    return {
        "citation_coverage": citation,
        "disclaimer_presence": disclaimer,
        "contradiction_detection_accuracy": contradiction,
        "gates": {
            "citation_coverage_gte_0_95": citation >= 0.95,
            "disclaimer_presence_eq_1_00": abs(disclaimer - 1.0) < 1e-9,
            "contradiction_accuracy_gte_0_70": contradiction >= 0.70,
        },
    }


def main() -> int:
    args = parse_args()
    root = Path(__file__).resolve().parents[1]
    logs_root = root / "logs"
    output_root = root / args.output_root
    output_root.mkdir(parents=True, exist_ok=True)

    run_log_dir = Path(args.run_log_dir) if args.run_log_dir else None
    if run_log_dir and not run_log_dir.is_absolute():
        run_log_dir = root / run_log_dir
    if not run_log_dir:
        run_log_dir = latest_run_log_dir(logs_root)
    if run_log_dir is None or not run_log_dir.exists():
        raise FileNotFoundError("Run log directory not found.")

    ts = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    bundle_dir = output_root / f"bundle_{ts}"
    bundle_dir.mkdir(parents=True, exist_ok=True)
    copied_files: list[str] = []

    copy_if_exists(root / "README.md", bundle_dir / "README.md", copied_files)
    copy_if_exists(root / "docker-compose.yml", bundle_dir / "docker-compose.yml", copied_files)
    copy_if_exists(root / "requirements.txt", bundle_dir / "requirements.txt", copied_files)
    copy_if_exists(root / "requirements-eval.txt", bundle_dir / "requirements-eval.txt", copied_files)
    copy_if_exists(root / ".env.example", bundle_dir / ".env.example", copied_files)
    copy_tree_if_exists(root / "docs", bundle_dir / "docs", copied_files)
    copy_tree_if_exists(root / "datasets", bundle_dir / "datasets", copied_files)
    copy_tree_if_exists(root / run_log_dir.relative_to(root), bundle_dir / "logs" / run_log_dir.name, copied_files)
    copy_if_exists(root / "logs" / "eval_report.json", bundle_dir / "logs" / "eval_report.json", copied_files)

    eval_reports_dir = root / "logs" / "eval_reports"
    if eval_reports_dir.exists():
        latest_eval_artifact = max(eval_reports_dir.glob("eval_*.json"), default=None, key=lambda p: p.stat().st_mtime)
        if latest_eval_artifact:
            copy_if_exists(
                latest_eval_artifact,
                bundle_dir / "logs" / "eval_reports" / latest_eval_artifact.name,
                copied_files,
            )
            md_artifact = latest_eval_artifact.with_suffix(".md")
            copy_if_exists(md_artifact, bundle_dir / "logs" / "eval_reports" / md_artifact.name, copied_files)

    eval_report_path = root / "logs" / "eval_report.json"
    eval_report = {}
    if eval_report_path.exists():
        eval_report = json.loads(eval_report_path.read_text(encoding="utf-8"))
    gate_metrics = extract_gate_metrics(eval_report) if eval_report else {}

    checksums = {}
    for file_str in copied_files:
        p = Path(file_str)
        if p.exists():
            checksums[str(p.relative_to(bundle_dir))] = sha256_file(p)

    manifest = {
        "created_at_utc": datetime.now(UTC).isoformat(),
        "run_log_dir": str(run_log_dir),
        "bundle_dir": str(bundle_dir),
        "file_count": len(checksums),
        "gate_metrics": gate_metrics,
        "checksums_sha256": checksums,
    }
    manifest_path = bundle_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    summary_lines = [
        "# Release Bundle Summary",
        "",
        f"- Created At (UTC): `{manifest['created_at_utc']}`",
        f"- Run Log Dir: `{manifest['run_log_dir']}`",
        f"- Files Included: `{manifest['file_count']}`",
    ]
    if gate_metrics:
        summary_lines.extend(
            [
                "",
                "## Gates",
                f"- citation_coverage: `{gate_metrics['citation_coverage']:.4f}`",
                f"- disclaimer_presence: `{gate_metrics['disclaimer_presence']:.4f}`",
                f"- contradiction_detection_accuracy: `{gate_metrics['contradiction_detection_accuracy']:.4f}`",
                f"- citation_coverage>=0.95: `{gate_metrics['gates']['citation_coverage_gte_0_95']}`",
                f"- disclaimer_presence==1.00: `{gate_metrics['gates']['disclaimer_presence_eq_1_00']}`",
                f"- contradiction_accuracy>=0.70: `{gate_metrics['gates']['contradiction_accuracy_gte_0_70']}`",
            ]
        )
    (bundle_dir / "SUMMARY.md").write_text("\n".join(summary_lines), encoding="utf-8")

    zip_base = output_root / f"bist_agentic_rag_release_{ts}"
    zip_path = shutil.make_archive(str(zip_base), "zip", root_dir=bundle_dir)
    print(json.dumps({"bundle_dir": str(bundle_dir), "zip_path": str(zip_path)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

