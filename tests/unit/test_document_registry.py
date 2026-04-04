from datetime import UTC, datetime
from pathlib import Path

from app.ingestion.registry import DocumentRegistry
from app.schemas import DocumentChunk, SourceType


def _chunk(doc_id: str, content: str, chunk_id: str) -> DocumentChunk:
    now = datetime.now(UTC)
    return DocumentChunk(
        content=content,
        ticker="ASELS",
        source_type=SourceType.NEWS,
        date=now,
        institution="AA",
        doc_id=doc_id,
        url=f"https://example.com/{doc_id}",
        published_at=now,
        retrieved_at=now,
        chunk_id=chunk_id,
        title="title",
    )


def test_registry_delta_dedup(tmp_path: Path) -> None:
    registry = DocumentRegistry(db_path=str(tmp_path / "registry.db"))
    chunks = [_chunk("doc-1", "content-a", "c1"), _chunk("doc-1", "content-a", "c2")]
    selected1, stats1 = registry.filter_chunks_for_delta(chunks, force_reingest=False, max_docs=10)
    assert len(selected1) == 2
    assert stats1["new"] == 1

    selected2, stats2 = registry.filter_chunks_for_delta(chunks, force_reingest=False, max_docs=10)
    assert len(selected2) == 0
    assert stats2["skipped"] == 1

    updated = [_chunk("doc-1", "content-b", "c3")]
    selected3, stats3 = registry.filter_chunks_for_delta(updated, force_reingest=False, max_docs=10)
    assert len(selected3) == 1
    assert stats3["updated"] == 1

