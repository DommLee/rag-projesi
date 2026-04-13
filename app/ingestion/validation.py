from __future__ import annotations

from typing import Any

from app.schemas import DocumentChunk, SourceType


MANDATORY_METADATA_FIELDS = (
    "ticker",
    "source_type",
    "publication_date",
    "institution",
    "notification_type",
    "url",
)


def normalize_source_type(value: str) -> SourceType:
    normalized = value.strip().lower()
    if normalized in {"broker_report", "brokerage"}:
        return SourceType.BROKERAGE
    return SourceType(normalized)


def normalize_notification_type(value: str) -> str:
    lowered = value.strip().lower()
    mapping = {
        "material event": "Material Event",
        "financial report": "Financial Report",
        "board decision": "Board Decision",
        "general assembly": "General Assembly",
    }
    return mapping.get(lowered, value.strip() or "General Assembly")


def validate_chunk_contract(chunk: DocumentChunk) -> tuple[bool, list[str]]:
    issues: list[str] = []
    for field in MANDATORY_METADATA_FIELDS:
        if field == "publication_date":
            if not chunk.publication_date:
                issues.append("missing.publication_date")
            continue
        if not getattr(chunk, field, None):
            issues.append(f"missing.{field}")
    if chunk.source_type not in set(SourceType):
        issues.append("invalid.source_type")
    if not (0.0 <= float(chunk.confidence) <= 1.0):
        issues.append("invalid.confidence")
    return len(issues) == 0, issues


def metadata_snapshot(chunk: DocumentChunk) -> dict[str, Any]:
    return {
        "ticker": chunk.ticker,
        "source_type": chunk.source_type.value,
        "publication_date": chunk.publication_date.isoformat() if chunk.publication_date else "",
        "institution": chunk.institution,
        "notification_type": chunk.notification_type,
        "url": chunk.url,
        "chunk_id": chunk.chunk_id,
        "ingest_date": chunk.ingest_date.isoformat(),
        "confidence": float(chunk.confidence),
        "source_channel": chunk.source_channel,
        "source_reliability": float(chunk.source_reliability),
        "author": chunk.author,
        "author_handle": chunk.author_handle,
        "engagement": int(chunk.engagement),
        "entity_aliases": list(chunk.entity_aliases),
        "discovered_via": chunk.discovered_via,
        "raw_doc_path": chunk.raw_doc_path,
        "analysis_cache_key": chunk.analysis_cache_key,
        "sentiment_score": float(chunk.sentiment_score),
        "sentiment_label": chunk.sentiment_label,
        "session_id": chunk.session_id,
        "upload_id": chunk.upload_id,
    }
