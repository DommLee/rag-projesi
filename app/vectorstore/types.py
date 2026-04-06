from __future__ import annotations

from datetime import datetime
from typing import Protocol

from app.schemas import DocumentChunk, SourceType


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

