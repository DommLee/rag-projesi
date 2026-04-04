from datetime import UTC, datetime

from app.agent.nodes import AgentNodes
from app.schemas import DocumentChunk, SourceType


def test_citation_generation() -> None:
    now = datetime.now(UTC)
    chunks = [
        DocumentChunk(
            content="Example",
            ticker="ASELS",
            source_type=SourceType.KAP,
            date=now,
            institution="KAP",
            doc_id="d1",
            url="https://example.com/1",
            published_at=now,
            retrieved_at=now,
            title="Title1",
            chunk_id="c1",
        ),
        DocumentChunk(
            content="Example2",
            ticker="ASELS",
            source_type=SourceType.KAP,
            date=now,
            institution="KAP",
            doc_id="d1",
            url="https://example.com/1",
            published_at=now,
            retrieved_at=now,
            title="Title1",
            chunk_id="c2",
        ),
    ]
    citations = AgentNodes._build_citations(chunks)
    assert len(citations) == 1
    assert citations[0].title == "Title1"

