# Trade-off Matrix

| Layer | Options Considered | Decision | Rationale |
|---|---|---|---|
| LLM Runtime | Ollama, OpenAI, Together | Ollama primary, provider fallback active | Local-first cost and latency control, fallback resilience for outages |
| Evaluation | Real judge, hybrid judge, heuristic-only | Heuristic-only default | Assignment demo reliability without API-key dependency; report marks model-judge as not-run |
| Retrieval | Vector-only, metadata-only, hybrid | Metadata-first + vector + time-decay | Improves ticker/date precision while keeping semantic recall |
| Agent Routing | Fixed linear graph, conditional graph | Conditional graph | Skips unnecessary re-retrieval when evidence is already sufficient |
| Guardrails | Citation count heuristic, claim-level grounding | Claim-level grounding | Stronger evidence enforcement for declarative statements |
| Vector Store | Milvus strict, Milvus with fallback | Milvus with configurable strict mode | Local dev continuity with option to enforce strict production behavior |
| Ingestion | Full reingest, delta registry | Delta/idempotent registry | Prevents duplicate growth and improves repeatability |
| Desktop Delivery | BAT only, GUI only, EXE onedir | GUI + EXE onedir | Better classroom demo UX with manageable packaging reliability |

