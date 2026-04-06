from datetime import UTC, datetime

from app.ingestion.chunking import RawDoc, build_chunks
from app.schemas import SourceType


def test_chunk_metadata_mandatory_fields() -> None:
    raw = RawDoc(
        ticker="ASELS",
        source_type=SourceType.KAP,
        institution="KAP",
        url="https://www.kap.org.tr",
        title="Example disclosure",
        text="A" * 2200,
        date=datetime.now(UTC),
        published_at=datetime.now(UTC),
        retrieved_at=datetime.now(UTC),
    )
    chunks = build_chunks(raw)
    assert len(chunks) >= 2
    for chunk in chunks:
        assert chunk.ticker == "ASELS"
        assert chunk.source_type == SourceType.KAP
        assert chunk.publication_date is not None
        assert chunk.date is not None
        assert chunk.institution
        assert chunk.notification_type
        assert chunk.doc_id
        assert chunk.url
        assert chunk.published_at
        assert chunk.retrieved_at
        assert chunk.ingest_date
        assert chunk.language
        assert 0 <= chunk.confidence <= 1
