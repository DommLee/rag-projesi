from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Protocol

import numpy as np

from app.config import get_settings
from app.models.embeddings import embed_text
from app.schemas import DocumentChunk, SourceType

logger = logging.getLogger(__name__)

try:
    from pymilvus import (  # type: ignore
        Collection,
        CollectionSchema,
        DataType,
        FieldSchema,
        connections,
        utility,
    )
except Exception:  # noqa: BLE001
    Collection = None
    CollectionSchema = None
    DataType = None
    FieldSchema = None
    connections = None
    utility = None


class VectorStore(Protocol):
    def upsert(self, chunks: list[DocumentChunk]) -> int:
        raise NotImplementedError

    def search(
        self,
        query: str,
        ticker: str | None,
        source_types: list[SourceType] | None,
        as_of_date: datetime | None,
        top_k: int = 8,
    ) -> list[DocumentChunk]:
        raise NotImplementedError

    def health(self) -> dict:
        raise NotImplementedError


def _to_ts(value: datetime) -> int:
    return int(value.timestamp())


def _from_ts(value: int) -> datetime:
    return datetime.fromtimestamp(value, tz=UTC)


class InMemoryVectorStore(VectorStore):
    def __init__(self) -> None:
        self._rows: list[tuple[list[float], DocumentChunk]] = []

    def upsert(self, chunks: list[DocumentChunk]) -> int:
        for chunk in chunks:
            vector = embed_text(chunk.content)
            self._rows.append((vector, chunk))
        return len(chunks)

    def search(
        self,
        query: str,
        ticker: str | None,
        source_types: list[SourceType] | None,
        as_of_date: datetime | None,
        top_k: int = 8,
    ) -> list[DocumentChunk]:
        qvec = np.array(embed_text(query))
        scored: list[tuple[float, DocumentChunk]] = []
        source_values = {s.value for s in source_types or []}

        for vec, chunk in self._rows:
            if ticker and chunk.ticker != ticker.upper():
                continue
            if source_values and chunk.source_type.value not in source_values:
                continue
            if as_of_date and chunk.date > as_of_date:
                continue
            cvec = np.array(vec)
            sim = float(np.dot(qvec, cvec))
            scored.append((sim, chunk))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [chunk for _, chunk in scored[:top_k]]

    def health(self) -> dict:
        return {"backend": "inmemory", "rows": len(self._rows)}


class MilvusVectorStore(VectorStore):
    def __init__(self) -> None:
        self.settings = get_settings()
        self.collection_name = self.settings.milvus_collection
        self._fallback = InMemoryVectorStore()
        self._connected = False
        self._collection = None
        self._connect_or_fallback()

    def _connect_or_fallback(self) -> None:
        if connections is None:
            logger.warning("pymilvus not available, using in-memory vector store.")
            return
        try:
            connections.connect(
                alias="default",
                host=self.settings.milvus_host,
                port=str(self.settings.milvus_port),
            )
            self._ensure_collection()
            self._connected = True
            logger.info("Connected to Milvus.")
        except Exception as exc:  # noqa: BLE001
            if self.settings.milvus_strict_mode:
                raise RuntimeError(f"Milvus strict mode enabled and connection failed: {exc}") from exc
            logger.warning("Milvus connection failed, fallback to in-memory: %s", exc)

    def _ensure_collection(self) -> None:
        assert utility and Collection and FieldSchema and CollectionSchema and DataType
        if utility.has_collection(self.collection_name):
            self._collection = Collection(self.collection_name)
            self._collection.load()
            return

        fields = [
            FieldSchema(name="chunk_id", dtype=DataType.VARCHAR, max_length=128, is_primary=True),
            FieldSchema(name="ticker", dtype=DataType.VARCHAR, max_length=24),
            FieldSchema(name="source_type", dtype=DataType.VARCHAR, max_length=32),
            FieldSchema(name="date_ts", dtype=DataType.INT64),
            FieldSchema(name="institution", dtype=DataType.VARCHAR, max_length=128),
            FieldSchema(name="doc_id", dtype=DataType.VARCHAR, max_length=128),
            FieldSchema(name="url", dtype=DataType.VARCHAR, max_length=1024),
            FieldSchema(name="title", dtype=DataType.VARCHAR, max_length=512),
            FieldSchema(name="content", dtype=DataType.VARCHAR, max_length=8192),
            FieldSchema(name="published_ts", dtype=DataType.INT64),
            FieldSchema(name="retrieved_ts", dtype=DataType.INT64),
            FieldSchema(name="language", dtype=DataType.VARCHAR, max_length=16),
            FieldSchema(name="confidence", dtype=DataType.FLOAT),
            FieldSchema(name="embedding", dtype=DataType.FLOAT_VECTOR, dim=self.settings.milvus_dim),
        ]
        schema = CollectionSchema(fields=fields, description="BIST RAG chunks")
        self._collection = Collection(name=self.collection_name, schema=schema)
        self._collection.create_index(
            field_name="embedding",
            index_params={"index_type": "IVF_FLAT", "metric_type": "IP", "params": {"nlist": 128}},
        )
        self._collection.load()

    def upsert(self, chunks: list[DocumentChunk]) -> int:
        if not self._connected or not self._collection:
            if self.settings.milvus_strict_mode:
                raise RuntimeError("Milvus strict mode enabled: in-memory fallback is not allowed for upsert.")
            return self._fallback.upsert(chunks)

        payload = [
            [chunk.chunk_id for chunk in chunks],
            [chunk.ticker for chunk in chunks],
            [chunk.source_type.value for chunk in chunks],
            [_to_ts(chunk.date) for chunk in chunks],
            [chunk.institution for chunk in chunks],
            [chunk.doc_id for chunk in chunks],
            [chunk.url for chunk in chunks],
            [chunk.title[:512] for chunk in chunks],
            [chunk.content[:8192] for chunk in chunks],
            [_to_ts(chunk.published_at) for chunk in chunks],
            [_to_ts(chunk.retrieved_at) for chunk in chunks],
            [chunk.language for chunk in chunks],
            [float(chunk.confidence) for chunk in chunks],
            [embed_text(chunk.content) for chunk in chunks],
        ]
        self._collection.insert(payload)
        self._collection.flush()
        return len(chunks)

    def search(
        self,
        query: str,
        ticker: str | None,
        source_types: list[SourceType] | None,
        as_of_date: datetime | None,
        top_k: int = 8,
    ) -> list[DocumentChunk]:
        if not self._connected or not self._collection:
            if self.settings.milvus_strict_mode:
                raise RuntimeError("Milvus strict mode enabled: in-memory fallback is not allowed for search.")
            return self._fallback.search(query, ticker, source_types, as_of_date, top_k)

        expr_parts: list[str] = []
        if ticker:
            expr_parts.append(f'ticker == "{ticker.upper()}"')
        if source_types:
            st_values = [s.value for s in source_types]
            st_expr = ",".join([f'"{s}"' for s in st_values])
            expr_parts.append(f"source_type in [{st_expr}]")
        if as_of_date:
            expr_parts.append(f"date_ts <= {_to_ts(as_of_date)}")

        expr = " and ".join(expr_parts) if expr_parts else ""
        output_fields = [
            "chunk_id",
            "ticker",
            "source_type",
            "date_ts",
            "institution",
            "doc_id",
            "url",
            "title",
            "content",
            "published_ts",
            "retrieved_ts",
            "language",
            "confidence",
        ]
        results = self._collection.search(
            data=[embed_text(query)],
            anns_field="embedding",
            param={"metric_type": "IP", "params": {"nprobe": 16}},
            limit=top_k,
            expr=expr,
            output_fields=output_fields,
        )

        chunks: list[DocumentChunk] = []
        for hit in results[0]:
            entity = hit.entity
            chunks.append(
                DocumentChunk(
                    content=entity.get("content"),
                    ticker=entity.get("ticker"),
                    source_type=SourceType(entity.get("source_type")),
                    date=_from_ts(entity.get("date_ts")),
                    institution=entity.get("institution"),
                    doc_id=entity.get("doc_id"),
                    url=entity.get("url"),
                    published_at=_from_ts(entity.get("published_ts")),
                    retrieved_at=_from_ts(entity.get("retrieved_ts")),
                    language=entity.get("language"),
                    confidence=float(entity.get("confidence")),
                    title=entity.get("title"),
                    chunk_id=entity.get("chunk_id"),
                )
            )
        return chunks

    def health(self) -> dict:
        if self._connected:
            return {
                "backend": "milvus",
                "collection": self.collection_name,
                "milvus_connected": True,
                "fallback_mode": "none",
                "strict_mode": self.settings.milvus_strict_mode,
            }
        fallback = self._fallback.health()
        fallback.update(
            {
                "milvus_connected": False,
                "fallback_mode": "inmemory",
                "strict_mode": self.settings.milvus_strict_mode,
            }
        )
        return fallback
