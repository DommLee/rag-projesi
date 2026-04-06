# Trade-off Matrix

| Layer | Options Considered | Decision | Rationale |
|---|---|---|---|
| LLM Runtime | Ollama, OpenAI, Together | Ollama primary, provider fallback active | Local-first cost and latency control, fallback resilience for outages |
| Evaluation | Real judge, hybrid judge, heuristic-only | Heuristic-only default | Assignment demo reliability without API-key dependency; report marks model-judge as not-run |
| Retrieval | Vector-only, metadata-only, hybrid | Metadata-first + vector + time-decay | Improves ticker/date precision while keeping semantic recall |
| Agent Routing | Fixed linear graph, conditional graph | Conditional graph | Skips unnecessary re-retrieval when evidence is already sufficient |
| Guardrails | Citation count heuristic, claim-level grounding | Claim-level grounding | Stronger evidence enforcement for declarative statements |
| Vector Store | Weaviate strict, Weaviate with fallback | Weaviate with configurable strict mode | Metadata-first filtering + hybrid retrieval + local dev continuity |
| Ingestion | Full reingest, delta registry | Delta/idempotent registry | Prevents duplicate growth and improves repeatability |
| Desktop Delivery | BAT only, GUI only, EXE onedir | GUI + EXE onedir | Better classroom demo UX with manageable packaging reliability |
