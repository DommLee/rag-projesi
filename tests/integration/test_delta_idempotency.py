from datetime import UTC, datetime
from pathlib import Path

from app.ingestion.registry import DocumentRegistry
from app.schemas import DocumentChunk, SourceType


def _chunk(doc_id: str, chunk_id: str, content: str) -> DocumentChunk:
    now = datetime.now(UTC)
    return DocumentChunk(
        content=content,
        ticker="ASELS",
        source_type=SourceType.KAP,
        date=now,
        institution="KAP",
        doc_id=doc_id,
        url=f"https://kap.org.tr/{doc_id}",
        published_at=now,
        retrieved_at=now,
        title="KAP",
        chunk_id=chunk_id,
    )


def test_delta_ingest_idempotency(tmp_path: Path) -> None:
    registry = DocumentRegistry(db_path=str(tmp_path / "registry.db"))
    first_batch = [
        _chunk("kap-1", "kap-1-c1", "Açıklama bir"),
        _chunk("kap-1", "kap-1-c2", "Açıklama bir devam"),
    ]
    selected_first, stats_first = registry.filter_chunks_for_delta(first_batch, max_docs=50)
    assert len(selected_first) == 2
    assert stats_first["new"] == 1

    selected_second, stats_second = registry.filter_chunks_for_delta(first_batch, max_docs=50)
    assert len(selected_second) == 0
    assert stats_second["skipped"] == 1
    assert stats_second["selected_chunks"] == 0

