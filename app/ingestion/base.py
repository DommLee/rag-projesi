from __future__ import annotations

from abc import ABC, abstractmethod

from app.schemas import DocumentChunk


class BaseIngestor(ABC):
    @abstractmethod
    def collect(self, **kwargs) -> list[DocumentChunk]:
        raise NotImplementedError

