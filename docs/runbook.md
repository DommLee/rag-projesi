# Runbook

## Fast Demo
1. `fast_demo.bat`
2. Open `http://localhost:18000/` (or fallback port printed by `30_run_api.bat`)
3. Run one `news` ingestion job and one `query/insight`.

## Full Assignment Run
1. `full_eval.bat`
2. Validate:
   - `/v1/health`
   - `/v1/ready`
   - `/v1/metrics`
   - `/v1/eval/report/latest`
3. Export latest report artifacts from `logs/eval_reports/`.
4. Build release package: `80_release_bundle.bat` (or run `99_full_pipeline.bat` which calls it automatically).
5. Generate GitHub readiness report: `90_github_ready.bat`.

## Manual API Checks
- `POST /v1/ingest/kap` with `delta_mode=true`
- `POST /v1/ingest/news` with RSS + HTML URLs
- `POST /v1/ingest/report` with at least one PDF
- `POST /v1/query` and confirm citations/time/disclaimer

## Full One-Shot
Use:
`set ALLOW_LOCAL_FALLBACK=1 && set SKIP_OLLAMA_PULL=1 && 99_full_pipeline.bat`
