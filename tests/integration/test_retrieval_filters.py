from datetime import UTC, datetime, timedelta

from app.retrieval.retriever import Retriever
from app.schemas import DocumentChunk, SourceType
from app.vectorstore.milvus_store import InMemoryVectorStore


def _mk_chunk(ticker: str, source: SourceType, days_ago: int, cid: str) -> DocumentChunk:
    dt = datetime.now(UTC) - timedelta(days=days_ago)
    return DocumentChunk(
        content=f"{ticker} {source.value} content {cid}",
        ticker=ticker,
        source_type=source,
        date=dt,
        institution="inst",
        doc_id=f"doc-{cid}",
        url=f"https://example.com/{cid}",
        published_at=dt,
        retrieved_at=dt,
        title="t",
        chunk_id=f"c-{cid}",
    )


def test_retrieval_filters_ticker_source_and_as_of_date() -> None:
    store = InMemoryVectorStore()
    store.upsert(
        [
            _mk_chunk("ASELS", SourceType.KAP, 1, "1"),
            _mk_chunk("ASELS", SourceType.NEWS, 120, "2"),
            _mk_chunk("THYAO", SourceType.KAP, 1, "3"),
        ]
    )
    retriever = Retriever(store)
    as_of = datetime.now(UTC) - timedelta(days=30)
    docs = retriever.retrieve(
        query="ASELS disclosures",
        ticker="ASELS",
        source_types=[SourceType.KAP, SourceType.NEWS],
        as_of_date=as_of,
        top_k=10,
    )
    assert all(doc.ticker == "ASELS" for doc in docs)
    assert all(doc.date <= as_of for doc in docs)
    assert all(doc.source_type in {SourceType.KAP, SourceType.NEWS} for doc in docs)


def test_retrieval_trace_has_expected_step_order() -> None:
    store = InMemoryVectorStore()
    store.upsert([_mk_chunk("ASELS", SourceType.KAP, 1, "trace")])
    retriever = Retriever(store)
    docs, trace = retriever.retrieve_with_trace(
        query="ASELS",
        ticker="ASELS",
        source_types=[SourceType.KAP],
        as_of_date=datetime.now(UTC),
        top_k=3,
    )
    assert len(docs) >= 1
    step_names = [step["name"] for step in trace["steps"]]
    assert step_names == ["vector_search", "time_decay_rerank"]
