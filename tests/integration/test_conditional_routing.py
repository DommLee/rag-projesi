from datetime import UTC, datetime, timedelta

from app.agent.graph import AgentGraph
from app.memory.claim_ledger import ClaimLedger
from app.models.providers import RoutedLLM
from app.retrieval.retriever import Retriever
from app.schemas import DocumentChunk, SourceType
from app.vectorstore.milvus_store import InMemoryVectorStore


def _chunk(idx: int, text: str) -> DocumentChunk:
    now = datetime.now(UTC) - timedelta(days=idx)
    return DocumentChunk(
        content=text,
        ticker="ASELS",
        source_type=SourceType.KAP,
        publication_date=now,
        date=now,
        institution="KAP",
        notification_type="Material Event",
        doc_id=f"doc-{idx}",
        url=f"https://example.com/{idx}",
        published_at=now,
        retrieved_at=now,
        title=f"title-{idx}",
        chunk_id=f"chunk-{idx}",
    )


def test_conditional_routing_skips_reretriever_when_evidence_is_sufficient(monkeypatch) -> None:
    store = InMemoryVectorStore()
    store.upsert([_chunk(i, "gelir artış güçlü onay") for i in range(1, 6)])
    retriever = Retriever(store)
    graph = AgentGraph(retriever=retriever, llm=RoutedLLM(), claim_ledger=ClaimLedger())
    graph._compiled = None  # force sequential path for deterministic assertion

    calls = {"reretriever": 0}
    original = graph.nodes.reretriever

    def wrapped(state):  # noqa: ANN001,ANN202
        calls["reretriever"] += 1
        return original(state)

    monkeypatch.setattr(graph.nodes, "reretriever", wrapped)
    graph.run(
        {
            "ticker": "ASELS",
            "question": "KAP narrative summary",
            "provider_pref": "mock",
            "as_of_date": datetime.now(UTC),
            "language": "bilingual",
            "session_id": "route-a",
        }
    )
    assert calls["reretriever"] == 0


def test_conditional_routing_calls_reretriever_when_evidence_is_low(monkeypatch) -> None:
    store = InMemoryVectorStore()
    store.upsert([_chunk(1, "tek kanıt")])
    retriever = Retriever(store)
    graph = AgentGraph(retriever=retriever, llm=RoutedLLM(), claim_ledger=ClaimLedger())
    graph._compiled = None

    calls = {"reretriever": 0}
    original = graph.nodes.reretriever

    def wrapped(state):  # noqa: ANN001,ANN202
        calls["reretriever"] += 1
        return original(state)

    monkeypatch.setattr(graph.nodes, "reretriever", wrapped)
    graph.run(
        {
            "ticker": "ASELS",
            "question": "KAP ve haber çelişiyor mu?",
            "provider_pref": "mock",
            "as_of_date": datetime.now(UTC),
            "language": "bilingual",
            "session_id": "route-b",
        }
    )
    assert calls["reretriever"] == 1

