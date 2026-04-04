# Trade-off Matrix

| Layer | Option | Strength | Weakness | Current Default |
|---|---|---|---|---|
| LLM | Ollama | Local, low cost | Variable quality by model | Primary |
| LLM | OpenAI | Strong Turkish/English quality | API cost | Optional real eval |
| LLM | Together | Fast prototyping | Third-party dependency | Fallback |
| Embedding | Local deterministic | Zero external dependency | Semantic quality low | Dev fallback |
| Embedding | OpenAI/Voyage/Nomic/Ollama | Better semantic retrieval | Key/model management | Configurable |
| Vector DB | Milvus | Production-grade scale | Infra complexity | Preferred |
| Vector DB | InMemory fallback | Fast local continuity | Non-persistent | Disabled in strict mode |
| Evaluation | Mock | Cheap/fast | Not academically strong | Baseline |
| Evaluation | Hybrid | Better realism-cost balance | Requires careful reporting | Recommended |
| Evaluation | Real | Best realism | Cost and latency | Final gate optional |

