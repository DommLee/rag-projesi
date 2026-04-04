# Release Checklist

## Pre-Release
- Run `99_full_pipeline.bat` (or `full_eval.bat`) with:
  - `ALLOW_LOCAL_FALLBACK=1` if Docker is unavailable
  - `SKIP_OLLAMA_PULL=1` if model pull should be skipped
- Confirm `logs/eval_report.json` exists and gate values are acceptable.
- Confirm `docs/latest_run_summary.md` exists and shows PASS on required gates.

## Required Artifacts
- Eval report: `logs/eval_report.json`
- Eval artifacts: `logs/eval_reports/eval_*.json` and `.md`
- Demo log: `logs/<run_id>/60_demo_flow.log`
- Run summary: `docs/latest_run_summary.md`
- Bundle manifest: `releases/bundle_*/manifest.json`
- Bundle zip: `releases/bist_agentic_rag_release_*.zip`

## Delivery
- Push source code and docs to GitHub.
- Attach latest release zip and mention run-id used for the bundle.
- Include rubric mapping and latest run summary links in README/PR.

