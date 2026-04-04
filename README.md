# BIST Agentic RAG v1.1 (Assignment-Pass First)

Agentic RAG system for Turkish equity intelligence (BIST/KAP/Broker/News), with explicit non-advisory guardrails.

## Core Capabilities
- KAP HTML ingestion + parsing
- News RSS/HTML ingestion
- Brokerage PDF ingestion + OCR fallback
- Agentic loop: `retrieve -> verify -> re-retrieve -> answer`
- Cross-source consistency analysis (`aligned|contradiction|inconclusive`)
- Bilingual TR/EN answers with citations and as-of awareness
- Mandatory disclaimer in all outputs

## Hard Ethical Rule
`This system does not provide investment advice.`

## Gap-Closure Features Added
- Delta/idempotent ingestion via SQLite `document_registry`
- Legal-safe crawler policy (robots + rate limit + backoff + failover feed)
- Embedding providers: `ollama`, `openai`, `voyage`, `nomic`, `local`
- Milvus strict mode (optional no-fallback)
- Retrieval trace logging (`metadata filter -> vector search -> time-decay rerank`)
- Hybrid evaluation modes (`mock|hybrid|real`) with rubric scoring
- Eval artifacts: JSON + Markdown report
- Empty-corpus auto-seeding for eval fixtures (explicitly marked in eval notes)
- Dashboard with job status, metrics, latest eval access, last errors

## API Endpoints
- `GET /` dashboard
- `POST /v1/query`
- `POST /v1/query/insight`
- `POST /v1/ingest/kap`
- `POST /v1/ingest/news`
- `POST /v1/ingest/report`
- `POST /v1/jobs/ingest/{kap|news|report}`
- `GET /v1/jobs`
- `GET /v1/jobs/{job_id}`
- `POST /v1/eval/run`
- `GET /v1/eval/report/latest`
- `GET /v1/health`
- `GET /v1/ready`
- `GET /v1/metrics`
- `GET /v1/diagnostics/{ticker}`

## Windows Profiles
- Desktop GUI app: `120_desktop_app.bat`
- Application launch: `100_run_app.bat`
- Application stop: `101_stop_app.bat`
- Fast demo: `fast_demo.bat`
- Full evaluation: `full_eval.bat`
- Full pipeline logs: `99_full_pipeline.bat`
- Optional fixture seeding step: `25_seed_eval_corpus.bat`
- Service cleanup step: `70_stop_services.bat`
- Release bundle step: `80_release_bundle.bat`
- GitHub readiness step: `90_github_ready.bat`
- Publish step: `95_publish_git.bat` (set `REPO_URL` for first push)

## Resilience Flags
- `SKIP_OLLAMA_PULL=1`: skip model pull in `00_setup.bat`
- `ALLOW_LOCAL_FALLBACK=1`: if Docker daemon is unavailable, run API/worker locally in `30_run_api.bat`

## Setup
1. Copy `.env.example` to `.env`
2. Configure keys if needed (`OPENAI_API_KEY`, `TOGETHER_API_KEY`, etc.)
3. Run one profile:
```bat
fast_demo.bat
```
or
```bat
full_eval.bat
```

## Port Fallback
`30_run_api.bat` selects the first free port from:
- `18000`
- `18001`
- `18002`
- `8088`

Selected port is persisted in `logs/.runtime_api_port` and reused by `40_smoke_test.bat`.

## Evaluation Modes
- `mock`: deterministic low-cost baseline
- `hybrid`: mix of mock + real provider where available
- `real`: fully real provider path

## Offline Eval Fixture Command
```bat
.venv\Scripts\python scripts\seed_eval_corpus.py --dataset-path datasets/eval_questions.json --only-if-empty
```

## Tests
```bash
python -m pytest -q
```

## Deliverable Docs
- [Architecture Diagram](/D:/rag projesi/docs/architecture.mmd)
- [Trade-off Matrix](/D:/rag projesi/docs/tradeoff_matrix.md)
- [Runbook](/D:/rag projesi/docs/runbook.md)
- [Troubleshooting](/D:/rag projesi/docs/troubleshooting.md)
- [Final Demo Script](/D:/rag projesi/docs/final_demo_script.md)
- [Rubric Mapping](/D:/rag projesi/docs/rubric_mapping.md)
- [Latest Run Summary](/D:/rag projesi/docs/latest_run_summary.md)
- [Release Checklist](/D:/rag projesi/docs/release_checklist.md)
- [GitHub Ready Status](/D:/rag projesi/docs/github_ready_status.md)
- [App Quickstart](/D:/rag projesi/docs/app_quickstart.md)
