# Latest Run Summary

- Mode: `heuristic`
- Effective Mode: `heuristic_only`
- Provider: `auto`
- Real Provider Available: `False`
- Total Questions: `15`
- Rubric Total: `100.0` / 100

## Acceptance Gates
- Citation Coverage >= 0.95: **PASS** (`1.0000`)
- Disclaimer Presence = 1.00: **PASS** (`1.0000`)
- Contradiction Detection Accuracy >= 0.75: **PASS** (`1.0000`)

## Gate Results (Runtime)
- citation_coverage_gte_0_95: **PASS**
- disclaimer_presence_eq_1_0: **PASS**
- contradiction_accuracy_gte_0_75: **PASS**
- hard_gate_pass_rate_gte_0_95: **PASS**

## Notes
- Seeded 45 local evaluation fixtures for 9 missing ticker corpora.
- LLM judge not used: missing API keys for real-provider evaluation.
- Evaluation mode effective: heuristic_only
- Live coverage ratio=0.3061, fresh_doc_ratio=0.0000, universe_processed_24h=15.