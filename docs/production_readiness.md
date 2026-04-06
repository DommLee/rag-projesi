# Production Readiness (v1.3)

## What is now production-grade
- Persistent job store (`app/jobs.py`) using SQLite
- CI pipeline (`.github/workflows/ci.yml`) with env validation + test run
- Environment preflight checker (`scripts/validate_env.py`)
- Docker context hygiene (`.dockerignore`)
- Health endpoint includes app version (`/v1/health`)

## Operational baseline
1. Validate env:
   `python scripts/validate_env.py --mode heuristic`
2. Run tests:
   `python -m pytest -q`
3. Start app:
   `100_run_app.bat`
4. Run full pipeline:
   `99_full_pipeline.bat`

## Recommended next steps
- Move SQLite registries (`document_registry`, `jobs`) to managed Postgres in cloud deployment.
- Add auth layer for API endpoints (`/v1/query`, `/v1/ingest/*`, `/v1/eval/run`).
- Add centralized observability sink (Langfuse / OpenTelemetry collector).
- Add nightly regression automation for `50_eval.bat`.

