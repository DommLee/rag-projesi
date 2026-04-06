from __future__ import annotations

import hashlib
import sqlite3
import threading
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

from app.schemas import DocumentChunk


class DocumentRegistry:
    def __init__(self, db_path: str = "data/document_registry.db") -> None:
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS document_registry (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    doc_id TEXT NOT NULL,
                    source_url TEXT NOT NULL,
                    source_type TEXT NOT NULL,
                    ticker TEXT NOT NULL,
                    doc_fingerprint TEXT NOT NULL,
                    published_at TEXT,
                    last_seen_at TEXT NOT NULL,
                    ingest_version INTEGER NOT NULL DEFAULT 1,
                    status TEXT NOT NULL,
                    UNIQUE(doc_id, source_url)
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_doc_registry_ticker_source ON document_registry(ticker, source_type)"
            )

    @staticmethod
    def _fingerprint(text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    def _upsert_document(
        self,
        *,
        doc_id: str,
        source_url: str,
        source_type: str,
        ticker: str,
        doc_fingerprint: str,
        published_at: str,
        force_reingest: bool,
    ) -> dict:
        now = datetime.now(UTC).isoformat()
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM document_registry WHERE doc_id=? AND source_url=?",
                (doc_id, source_url),
            ).fetchone()

            if row is None:
                conn.execute(
                    """
                    INSERT INTO document_registry (
                        doc_id, source_url, source_type, ticker, doc_fingerprint,
                        published_at, last_seen_at, ingest_version, status
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?)
                    """,
                    (
                        doc_id,
                        source_url,
                        source_type,
                        ticker,
                        doc_fingerprint,
                        published_at,
                        now,
                        "new",
                    ),
                )
                return {"action": "new", "ingest_version": 1}

            same_fingerprint = row["doc_fingerprint"] == doc_fingerprint
            if same_fingerprint and not force_reingest:
                conn.execute(
                    "UPDATE document_registry SET last_seen_at=?, status=? WHERE id=?",
                    (now, "unchanged", row["id"]),
                )
                return {"action": "skipped", "ingest_version": int(row["ingest_version"])}

            new_version = int(row["ingest_version"]) + 1
            conn.execute(
                """
                UPDATE document_registry
                SET doc_fingerprint=?, published_at=?, last_seen_at=?, ingest_version=?, status=?
                WHERE id=?
                """,
                (
                    doc_fingerprint,
                    published_at,
                    now,
                    new_version,
                    "forced" if force_reingest else "updated",
                    row["id"],
                ),
            )
            return {
                "action": "forced" if force_reingest else "updated",
                "ingest_version": new_version,
            }

    def filter_chunks_for_delta(
        self,
        chunks: list[DocumentChunk],
        *,
        force_reingest: bool = False,
        max_docs: int = 100,
    ) -> tuple[list[DocumentChunk], dict]:
        with self._lock:
            groups: dict[tuple[str, str], list[DocumentChunk]] = defaultdict(list)
            for chunk in chunks:
                groups[(chunk.doc_id, chunk.url)].append(chunk)

            selected: list[DocumentChunk] = []
            stats = {"total_docs_seen": 0, "new": 0, "updated": 0, "forced": 0, "skipped": 0}

            for idx, ((doc_id, source_url), doc_chunks) in enumerate(groups.items()):
                if idx >= max_docs:
                    break
                stats["total_docs_seen"] += 1

                representative = doc_chunks[0]
                merged_content = "\n".join(c.content for c in doc_chunks)
                fingerprint = self._fingerprint(merged_content)

                outcome = self._upsert_document(
                    doc_id=doc_id,
                    source_url=source_url,
                    source_type=representative.source_type.value,
                    ticker=representative.ticker,
                    doc_fingerprint=fingerprint,
                    published_at=representative.published_at.isoformat(),
                    force_reingest=force_reingest,
                )
                action = outcome["action"]
                stats[action] += 1
                if action != "skipped":
                    for chunk in doc_chunks:
                        chunk.metadata["ingest_version"] = outcome["ingest_version"]
                    selected.extend(doc_chunks)

            stats["selected_docs"] = stats["new"] + stats["updated"] + stats["forced"]
            stats["selected_chunks"] = len(selected)
            seen = max(1, stats["total_docs_seen"])
            stats["dedup_rate"] = round(stats["skipped"] / seen, 4)
            return selected, stats

