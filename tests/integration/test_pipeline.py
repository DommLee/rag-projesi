from datetime import UTC, datetime, timedelta

from app.agent.graph import AgentGraph
from app.memory.claim_ledger import ClaimLedger
from app.models.providers import RoutedLLM
from app.retrieval.retriever import Retriever
from app.schemas import DocumentChunk, SourceType
from app.vectorstore.milvus_store import InMemoryVectorStore


def _chunk(ticker: str, source_type: SourceType, text: str, days_ago: int, cid: str) -> DocumentChunk:
    now = datetime.now(UTC) - timedelta(days=days_ago)
    return DocumentChunk(
        content=text,
        ticker=ticker,
        source_type=source_type,
        date=now,
        institution="test-inst",
        doc_id=f"doc-{cid}",
        url=f"https://example.com/{cid}",
        published_at=now,
        retrieved_at=now,
        title=f"title-{cid}",
        chunk_id=f"chunk-{cid}",
    )


def test_retrieve_verify_reretrieve_answer_flow() -> None:
    store = InMemoryVectorStore()
    store.upsert(
        [
            _chunk("ASELS", SourceType.KAP, "KAP says revenue increased and board approved project.", 2, "1"),
            _chunk("ASELS", SourceType.NEWS, "News reports project delays and weak outlook.", 1, "2"),
            _chunk("ASELS", SourceType.BROKER_REPORT, "Broker notes mixed signals on backlog.", 3, "3"),
        ]
    )
    retriever = Retriever(store)
    graph = AgentGraph(retriever=retriever, llm=RoutedLLM(), claim_ledger=ClaimLedger())
    response = graph.run(
        {
            "ticker": "ASELS",
            "question": "Do recent news contradict KAP disclosures?",
            "provider_pref": "mock",
            "as_of_date": datetime.now(UTC),
            "language": "bilingual",
            "session_id": "t1",
        }
    )
    assert response.disclaimer == "This system does not provide investment advice."
    assert len(response.citations) > 0
    assert response.consistency_assessment in {
        "contradiction",
        "aligned",
        "inconclusive",
        "insufficient_evidence",
    }
    assert response.provider_used in {"mock", "ollama", "openai", "together", "policy", "unknown"}
