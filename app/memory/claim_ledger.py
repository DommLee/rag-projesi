from __future__ import annotations

import hashlib
import logging
import sqlite3
import threading
from datetime import UTC, datetime
from pathlib import Path

logger = logging.getLogger(__name__)


class ClaimLedger:
    """Immutable hash registry for cited claims.

    Used to detect repeated unsupported statements across the agent's run
    history. The ledger keeps an in-memory view for fast checks and, when a
    ``db_path`` is supplied, mirrors every event into a SQLite file so that
    the registry survives across process restarts. This is the project's
    custom memory policy referenced in ``docs/rubric_mapping.md``.

    Schema is intentionally tiny:

        claims(claim_hash TEXT PRIMARY KEY,
               supported INTEGER NOT NULL,
               first_seen TEXT NOT NULL,
               last_seen  TEXT NOT NULL,
               occurrences INTEGER NOT NULL DEFAULT 1,
               sample_text TEXT)
    """

    def __init__(self, db_path: str | Path | None = None) -> None:
        self._claim_hashes: set[str] = set()
        self._unsupported_hashes: set[str] = set()
        self._events: list[dict] = []
        self._lock = threading.RLock()
        self._db_path = Path(db_path) if db_path else None
        self._conn: sqlite3.Connection | None = None
        if self._db_path is not None:
            self._init_db()
            self._hydrate_from_db()

    # ------------------------------------------------------------------ #
    # Persistence helpers
    # ------------------------------------------------------------------ #
    def _init_db(self) -> None:
        try:
            self._db_path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(
                str(self._db_path),
                check_same_thread=False,
                isolation_level=None,  # autocommit
            )
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS claims (
                    claim_hash TEXT PRIMARY KEY,
                    supported INTEGER NOT NULL,
                    first_seen TEXT NOT NULL,
                    last_seen TEXT NOT NULL,
                    occurrences INTEGER NOT NULL DEFAULT 1,
                    sample_text TEXT
                )
                """
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_claims_supported ON claims(supported)"
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("ClaimLedger SQLite init failed at %s: %s", self._db_path, exc)
            self._conn = None

    def _hydrate_from_db(self) -> None:
        if self._conn is None:
            return
        try:
            for row in self._conn.execute(
                "SELECT claim_hash, supported FROM claims"
            ):
                claim_hash, supported = row[0], int(row[1])
                self._claim_hashes.add(claim_hash)
                if supported == 0:
                    self._unsupported_hashes.add(claim_hash)
        except Exception as exc:  # noqa: BLE001
            logger.warning("ClaimLedger hydrate failed: %s", exc)

    def _persist(self, claim_hash: str, supported: bool, sample_text: str) -> None:
        if self._conn is None:
            return
        ts = datetime.now(UTC).isoformat()
        try:
            self._conn.execute(
                """
                INSERT INTO claims(claim_hash, supported, first_seen, last_seen, occurrences, sample_text)
                VALUES (?, ?, ?, ?, 1, ?)
                ON CONFLICT(claim_hash) DO UPDATE SET
                    supported = MIN(claims.supported, excluded.supported),
                    last_seen = excluded.last_seen,
                    occurrences = claims.occurrences + 1
                """,
                (claim_hash, 1 if supported else 0, ts, ts, sample_text[:280]),
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("ClaimLedger persist failed: %s", exc)

    # ------------------------------------------------------------------ #
    # Public API (compatible with the previous in-memory ledger)
    # ------------------------------------------------------------------ #
    @staticmethod
    def _hash_claim(claim: str) -> str:
        return hashlib.sha256(claim.strip().lower().encode("utf-8")).hexdigest()

    def register(self, claim: str, supported: bool) -> str:
        claim_text = claim.strip()
        claim_hash = self._hash_claim(claim_text)
        with self._lock:
            self._claim_hashes.add(claim_hash)
            if not supported:
                self._unsupported_hashes.add(claim_hash)
            self._events.append(
                {
                    "claim_hash": claim_hash,
                    "supported": supported,
                    "ts": datetime.now(UTC).isoformat(),
                }
            )
            self._persist(claim_hash, supported, claim_text)
        return claim_hash

    def is_repeated_unsupported(self, claim: str) -> bool:
        claim_hash = self._hash_claim(claim)
        with self._lock:
            return claim_hash in self._unsupported_hashes

    def stats(self) -> dict:
        with self._lock:
            total = len(self._claim_hashes)
            unsupported = len(self._unsupported_hashes)
            persisted = 0
            if self._conn is not None:
                try:
                    cursor = self._conn.execute("SELECT COUNT(*) FROM claims")
                    row = cursor.fetchone()
                    persisted = int(row[0]) if row else 0
                except Exception:  # noqa: BLE001
                    persisted = 0
            return {
                "total_claims": total,
                "unsupported_claims": unsupported,
                "unsupported_ratio": 0.0 if total == 0 else unsupported / total,
                "persistent_db": str(self._db_path) if self._db_path else "",
                "persistent_count": persisted,
            }

    def close(self) -> None:
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception:  # noqa: BLE001
                pass
            self._conn = None
