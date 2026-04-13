from __future__ import annotations

import json
import logging
import uuid
from datetime import UTC, datetime

import httpx

from app.config import get_settings
from app.ingestion.validation import metadata_snapshot, validate_chunk_contract
from app.models.embeddings import embed_text
from app.schemas import DocumentChunk, SourceType
from app.vectorstore.milvus_store import InMemoryVectorStore
from app.vectorstore.types import VectorStore

logger = logging.getLogger(__name__)


def _ensure_utc(dt: datetime | None) -> datetime:
    value = dt or datetime.now(UTC)
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


class WeaviateVectorStore(VectorStore):
    def __init__(self) -> None:
        self.settings = get_settings()
        self.base_url = self.settings.weaviate_url.rstrip("/")
        self.class_name = self.settings.weaviate_class_name
        self.strict_mode = self.settings.weaviate_strict_mode
        self._fallback = InMemoryVectorStore()
        self._connected = False
        self._client = httpx.Client(timeout=5.0)
        self._connect_or_fallback()

    def _connect_or_fallback(self) -> None:
        try:
            ready = self._client.get(f"{self.base_url}/v1/.well-known/ready")
            ready.raise_for_status()
            self._ensure_schema()
            self._connected = True
            logger.info("Connected to Weaviate at %s", self.base_url)
        except Exception as exc:  # noqa: BLE001
            if self.strict_mode:
                raise RuntimeError(f"Weaviate strict mode enabled and connection failed: {exc}") from exc
            logger.warning("Weaviate connection failed, using in-memory fallback: %s", exc)

    def _ensure_schema(self) -> None:
        schema_resp = self._client.get(f"{self.base_url}/v1/schema/{self.class_name}")
        if schema_resp.status_code == 200:
            return
        payload = {
            "class": self.class_name,
            "description": "BIST Agentic RAG chunks",
            "vectorizer": "none",
            "properties": [
                {"name": "chunk_id", "dataType": ["text"]},
                {"name": "ticker", "dataType": ["text"]},
                {"name": "source_type", "dataType": ["text"]},
                {"name": "publication_date", "dataType": ["date"]},
                {"name": "date", "dataType": ["date"]},
                {"name": "institution", "dataType": ["text"]},
                {"name": "notification_type", "dataType": ["text"]},
                {"name": "doc_id", "dataType": ["text"]},
                {"name": "url", "dataType": ["text"]},
                {"name": "title", "dataType": ["text"]},
                {"name": "content", "dataType": ["text"]},
                {"name": "published_at", "dataType": ["date"]},
                {"name": "retrieved_at", "dataType": ["date"]},
                {"name": "ingest_date", "dataType": ["date"]},
                {"name": "language", "dataType": ["text"]},
                {"name": "confidence", "dataType": ["number"]},
                {"name": "sentiment_score", "dataType": ["number"]},
                {"name": "sentiment_label", "dataType": ["text"]},
                {"name": "metadata_json", "dataType": ["text"]},
            ],
        }
        response = self._client.post(f"{self.base_url}/v1/schema", json=payload)
        if response.status_code not in {200, 201, 422}:
            response.raise_for_status()

    def upsert(self, chunks: list[DocumentChunk]) -> int:
        if not self._connected:
            if self.strict_mode:
                raise RuntimeError("Weaviate strict mode enabled: in-memory fallback is not allowed for upsert.")
            return self._fallback.upsert(chunks)

        batch_objects = []
        for chunk in chunks:
            ok, issues = validate_chunk_contract(chunk)
            if not ok:
                logger.warning("Skipping chunk %s due to contract issues: %s", chunk.chunk_id, ",".join(issues))
                continue
            batch_objects.append(
                {
                    "class": self.class_name,
                    "id": str(uuid.uuid5(uuid.NAMESPACE_URL, chunk.chunk_id)),
                    "vector": embed_text(chunk.content),
                    "properties": {
                        "chunk_id": chunk.chunk_id,
                        "ticker": chunk.ticker,
                        "source_type": chunk.source_type.value,
                        "publication_date": _ensure_utc(chunk.publication_date).isoformat(),
                        "date": _ensure_utc(chunk.date).isoformat(),
                        "institution": chunk.institution,
                        "notification_type": chunk.notification_type,
                        "doc_id": chunk.doc_id,
                        "url": chunk.url,
                        "title": chunk.title[:512],
                        "content": chunk.content[:8192],
                        "published_at": _ensure_utc(chunk.published_at).isoformat(),
                        "retrieved_at": _ensure_utc(chunk.retrieved_at).isoformat(),
                        "ingest_date": datetime.combine(chunk.ingest_date, datetime.min.time(), tzinfo=UTC).isoformat(),
                        "language": chunk.language,
                        "confidence": float(chunk.confidence),
                        "sentiment_score": float(chunk.sentiment_score),
                        "sentiment_label": chunk.sentiment_label,
                        "metadata_json": json.dumps(metadata_snapshot(chunk), ensure_ascii=False),
                    },
                }
            )
        if not batch_objects:
            return 0
        response = self._client.post(f"{self.base_url}/v1/batch/objects", json={"objects": batch_objects})
        response.raise_for_status()
        return len(batch_objects)

    @staticmethod
    def _where_clause(
        ticker: str | None,
        source_types: list[SourceType] | None,
        as_of_date: datetime | None,
    ) -> str:
        operands = []
        if ticker:
            operands.append('{path:["ticker"],operator:Equal,valueText:"%s"}' % ticker.upper())
        if source_types:
            if len(source_types) == 1:
                operands.append(
                    '{path:["source_type"],operator:Equal,valueText:"%s"}' % source_types[0].value
                )
            else:
                or_parts = ",".join(
                    '{path:["source_type"],operator:Equal,valueText:"%s"}' % s.value
                    for s in source_types
                )
                operands.append("{operator:Or,operands:[%s]}" % or_parts)
        if as_of_date:
            operands.append(
                '{path:["publication_date"],operator:LessThanEqual,valueDate:"%s"}'
                % _ensure_utc(as_of_date).isoformat()
            )
        if not operands:
            return ""
        if len(operands) == 1:
            return "where:%s" % operands[0]
        return "where:{operator:And,operands:[%s]}" % ",".join(operands)

    def search(
        self,
        query: str,
        ticker: str | None,
        source_types: list[SourceType] | None,
        as_of_date: datetime | None,
        top_k: int = 8,
        alpha: float | None = None,
    ) -> list[DocumentChunk]:
        if not self._connected:
            if self.strict_mode:
                raise RuntimeError("Weaviate strict mode enabled: in-memory fallback is not allowed for search.")
            return self._fallback.search(query, ticker, source_types, as_of_date, top_k)

        where_clause = self._where_clause(ticker, source_types, as_of_date)
        vector = embed_text(query)
        escaped_query = json.dumps(query)
        hybrid_alpha = alpha if alpha is not None else self.settings.weaviate_hybrid_alpha_default
        hybrid_alpha = max(0.0, min(1.0, float(hybrid_alpha)))
        gql = f"""
        {{
          Get {{
            {self.class_name}(
              hybrid: {{query: {escaped_query}, vector: {json.dumps(vector)}, alpha: {hybrid_alpha}}}
              {where_clause}
              limit: {top_k}
            ) {{
              chunk_id
              ticker
              source_type
              publication_date
              date
              institution
              notification_type
              doc_id
              url
              title
              content
              published_at
              retrieved_at
              ingest_date
              language
              confidence
              sentiment_score
              sentiment_label
            }}
          }}
        }}
        """
        response = self._client.post(f"{self.base_url}/v1/graphql", json={"query": gql})
        if response.status_code >= 400:
            response.raise_for_status()
        payload = response.json()
        if payload.get("errors"):
            # Fallback to plain vector search if hybrid query is not available.
            gql = f"""
            {{
              Get {{
                {self.class_name}(
                  nearVector: {{vector: {json.dumps(vector)}}}
                  {where_clause}
                  limit: {top_k}
                ) {{
                  chunk_id
                  ticker
                  source_type
                  publication_date
                  date
                  institution
                  notification_type
                  doc_id
                  url
                  title
                  content
                  published_at
                  retrieved_at
                  ingest_date
                  language
                  confidence
                  sentiment_score
                  sentiment_label
                }}
              }}
            }}
            """
            response = self._client.post(f"{self.base_url}/v1/graphql", json={"query": gql})
            response.raise_for_status()
            payload = response.json()
        rows = payload.get("data", {}).get("Get", {}).get(self.class_name, [])
        chunks: list[DocumentChunk] = []
        for row in rows:
            try:
                chunks.append(
                    DocumentChunk(
                        content=row.get("content", ""),
                        ticker=row.get("ticker", ""),
                        source_type=SourceType(row.get("source_type", "news")),
                        publication_date=datetime.fromisoformat(
                            row.get("publication_date", datetime.now(UTC).isoformat()).replace("Z", "+00:00")
                        ),
                        date=datetime.fromisoformat(
                            row.get("date", datetime.now(UTC).isoformat()).replace("Z", "+00:00")
                        ),
                        institution=row.get("institution", "unknown"),
                        notification_type=row.get("notification_type", "General Assembly"),
                        doc_id=row.get("doc_id", ""),
                        url=row.get("url", ""),
                        published_at=datetime.fromisoformat(
                            row.get("published_at", datetime.now(UTC).isoformat()).replace("Z", "+00:00")
                        ),
                        retrieved_at=datetime.fromisoformat(
                            row.get("retrieved_at", datetime.now(UTC).isoformat()).replace("Z", "+00:00")
                        ),
                        language=row.get("language", "tr"),
                        confidence=float(row.get("confidence", 0.0)),
                        title=row.get("title", ""),
                        chunk_id=row.get("chunk_id", ""),
                        sentiment_score=float(row.get("sentiment_score", 0.0) or 0.0),
                        sentiment_label=row.get("sentiment_label", "neutral"),
                    )
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("Skipping malformed Weaviate row: %s", exc)
        return chunks

    def health(self) -> dict:
        if self._connected:
            return {
                "backend": "weaviate",
                "weaviate_url": self.base_url,
                "weaviate_class": self.class_name,
                "weaviate_connected": True,
                "fallback_mode": "none",
                "strict_mode": self.strict_mode,
            }
        fallback = self._fallback.health()
        fallback.update(
            {
                "backend": "weaviate_fallback",
                "weaviate_url": self.base_url,
                "weaviate_class": self.class_name,
                "weaviate_connected": False,
                "fallback_mode": "inmemory",
                "strict_mode": self.strict_mode,
            }
        )
        return fallback
