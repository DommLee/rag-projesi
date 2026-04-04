from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Configure git remote and push current branch")
    parser.add_argument("--repo-url", default="", help="Remote repository URL (optional if remote already exists)")
    parser.add_argument("--remote", default="origin")
    parser.add_argument("--branch", default="", help="Branch to push (default: current branch)")
    return parser.parse_args()


def run_git(args: list[str], cwd: Path) -> tuple[int, str]:
    proc = subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=False,
    )
    output = "\n".join([p for p in [(proc.stdout or "").strip(), (proc.stderr or "").strip()] if p]).strip()
    return proc.returncode, output


def main() -> int:
    args = parse_args()
    root = Path(__file__).resolve().parents[1]

    rc, current_branch = run_git(["branch", "--show-current"], root)
    if rc != 0 or not current_branch:
        raise RuntimeError(f"Failed to detect current branch: {current_branch}")
    branch = args.branch.strip() or current_branch.strip()

    rc, remote_url = run_git(["config", "--get", f"remote.{args.remote}.url"], root)
    has_remote = rc == 0 and bool(remote_url.strip())

    repo_url = args.repo_url.strip()
    if repo_url:
        if has_remote:
            if remote_url.strip() != repo_url:
                rc, out = run_git(["remote", "set-url", args.remote, repo_url], root)
                if rc != 0:
                    raise RuntimeError(f"Failed to set remote URL: {out}")
        else:
            rc, out = run_git(["remote", "add", args.remote, repo_url], root)
            if rc != 0:
                raise RuntimeError(f"Failed to add remote: {out}")
    elif not has_remote:
        raise RuntimeError("No remote configured. Provide --repo-url or set remote first.")

    rc, push_out = run_git(["push", "-u", args.remote, branch], root)
    if rc != 0:
        raise RuntimeError(f"Push failed: {push_out}")

    result = {
        "remote": args.remote,
        "branch": branch,
        "push": "ok",
    }
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

