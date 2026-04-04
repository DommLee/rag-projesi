from datetime import UTC, datetime

from app.agent.graph import AgentGraph
from app.memory.claim_ledger import ClaimLedger
from app.models.providers import RoutedLLM
from app.retrieval.retriever import Retriever
from app.vectorstore.milvus_store import InMemoryVectorStore


def test_guardrail_blocks_investment_advice_request() -> None:
    store = InMemoryVectorStore()
    retriever = Retriever(store)
    graph = AgentGraph(retriever=retriever, llm=RoutedLLM(), claim_ledger=ClaimLedger())
    response = graph.run(
        {
            "ticker": "ASELS",
            "question": "ASELS için al sat önerin nedir?",
            "provider_pref": "mock",
            "as_of_date": datetime.now(UTC),
            "language": "bilingual",
            "session_id": "policy",
        }
    )
    assert response.blocked is True
    assert "investment advice" in response.answer_en.lower()
    assert response.consistency_assessment == "blocked_policy"

