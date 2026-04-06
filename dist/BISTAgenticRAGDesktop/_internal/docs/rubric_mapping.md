# Rubric Mapping (100 pts)

## Data Diversity (20)
- Evidence: multi-source retrieval (`kap`, `news`, `broker_report`)
- Source: `logs/eval_report.json -> heuristic_metrics.data_diversity`

## Retrieval Quality (20)
- Evidence: claim-level citation coverage
- Source: `logs/eval_report.json -> citation_coverage`

## Agentic Logic (15)
- Evidence: conditional routing + contradiction accuracy
- Source: `logs/eval_report.json -> contradiction_detection_accuracy`, `gate_results`

## Memory & Narrative (10)
- Evidence: narrative diagnostics + claim ledger + weekly snapshots
- Source: `/v1/diagnostics/{ticker}` response

## Ethics & Guardrails (15)
- Evidence: pre-answer policy refusal + mandatory disclaimer + claim grounding fallback
- Source: `logs/eval_report.json -> disclaimer_presence`, `gate_results`

## Evaluation Report (10)
- Evidence: heuristic metrics + gate results + rubric breakdown + artifacts
- Source: `logs/eval_report.json`, `logs/eval_reports/*.md`

## Demo & Docs (10)
- Evidence: scripted demo flow, latest summary, architecture/tradeoff docs, desktop EXE guide
- Source: `docs/final_demo_script.md`, `docs/latest_run_summary.md`, `docs/tradeoff_matrix.md`, `releases/desktop/README_EXE.md`

