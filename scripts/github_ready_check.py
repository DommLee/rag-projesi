from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate GitHub readiness status")
    parser.add_argument("--output", default="docs/github_ready_status.md")
    return parser.parse_args()


def run_git(args: list[str], cwd: Path) -> tuple[int, str]:
    proc = subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=False,
    )
    out = (proc.stdout or "").strip()
    err = (proc.stderr or "").strip()
    combined = "\n".join([part for part in [out, err] if part]).strip()
    return proc.returncode, combined


def main() -> int:
    args = parse_args()
    root = Path(__file__).resolve().parents[1]

    critical_files = [
        root / "README.md",
        root / "docker-compose.yml",
        root / "docs" / "latest_run_summary.md",
        root / "logs" / "eval_report.json",
    ]
    artifacts_ok = all(path.exists() for path in critical_files)
    missing = [str(path.relative_to(root)) for path in critical_files if not path.exists()]

    release_zip = None
    release_dir = root / "releases"
    if release_dir.exists():
        zips = sorted(release_dir.glob("bist_agentic_rag_release_*.zip"), key=lambda p: p.stat().st_mtime)
        if zips:
            release_zip = zips[-1]

    rc_branch, branch_out = run_git(["rev-parse", "--abbrev-ref", "HEAD"], root)
    branch = branch_out if rc_branch == 0 else "unknown"
    if rc_branch != 0 and ("unknown revision" in branch_out.lower() or "ambiguous argument 'head'" in branch_out.lower()):
        rc_symbolic, symbolic_out = run_git(["symbolic-ref", "--short", "HEAD"], root)
        if rc_symbolic == 0:
            branch = f"{symbolic_out} (unborn/no-commit)"
        else:
            branch = "unborn/no-commit"

    rc_remote, remote_out = run_git(["remote", "-v"], root)
    has_remote = rc_remote == 0 and bool(remote_out.strip())

    rc_status, status_out = run_git(["status", "--short"], root)
    dirty_count = len([line for line in status_out.splitlines() if line.strip()]) if rc_status == 0 else -1

    status_obj = {
        "artifacts_ok": artifacts_ok,
        "missing_critical_files": missing,
        "latest_release_zip": str(release_zip) if release_zip else "",
        "git_branch": branch,
        "git_remote_configured": has_remote,
        "git_uncommitted_items": dirty_count,
    }

    lines = [
        "# GitHub Ready Status",
        "",
        f"- Artifacts OK: `{artifacts_ok}`",
        f"- Git Branch: `{branch}`",
        f"- Git Remote Configured: `{has_remote}`",
        f"- Uncommitted Items: `{dirty_count}`",
        f"- Latest Release Zip: `{status_obj['latest_release_zip'] or 'N/A'}`",
    ]
    if missing:
        lines.extend(["", "## Missing Critical Files"])
        for item in missing:
            lines.append(f"- {item}")
    if not has_remote:
        lines.extend(
            [
                "",
                "## Next Step",
                "- Configure remote and push:",
                "  `git remote add origin <repo-url>`",
                "  `git push -u origin <branch>`",
            ]
        )
    if "unborn" in branch:
        lines.extend(
            [
                "",
                "## Initial Commit Needed",
                "- Create first commit before push:",
                "  `git add .`",
                "  `git commit -m \"Initial BIST Agentic RAG release\"`",
            ]
        )

    out_path = root / args.output
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps(status_obj, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
