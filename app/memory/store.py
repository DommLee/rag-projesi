from __future__ import annotations

import json
import logging
import sqlite3
import threading
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from app.config import get_settings

logger = logging.getLogger(__name__)


class MemoryStore:
    """Mem0-style lightweight tiered memory.

    Tiers
    -----
    1. **Session memory** — short TTL, in-process only. Holds per-session
       hints (last questions, last tickers, last citations) and is cleared
       automatically after ``session_ttl_hours``.
    2. **Ticker narrative weekly snapshots** — durable, persisted into a
       small SQLite file (``data/memory_store.db`` by default) so that the
       agent can answer "how has the narrative changed over time?" even
       after a restart. Each snapshot holds a short summary plus the dominant
       themes for one ISO week.
    3. **Evidence memory** — handled by ``ClaimLedger`` (separate DB).

    The class keeps the same public method shape as the previous in-memory
    implementation, so existing callers do not need any changes.
    """

    def __init__(self, db_path: str | Path | None = None) -> None:
        self._session_data: dict[str, tuple[datetime, dict[str, Any]]] = {}
        self._ticker_snapshots: dict[str, dict[str, Any]] = defaultdict(dict)
        self._ttl = timedelta(hours=get_settings().session_ttl_hours)
        self._lock = threading.RLock()

        resolved_path: Path | None
        if db_path is not None:
            resolved_path = Path(db_path)
        else:
            settings = get_settings()
            jobs_path = Path(settings.jobs_db_path)
            resolved_path = jobs_path.parent / "memory_store.db"
        self._db_path = resolved_path
        self._conn: sqlite3.Connection | None = None
        if self._db_path is not None:
            self._init_db()
            self._hydrate_from_db()

    # ------------------------------------------------------------------ #
    # SQLite plumbing
    # ------------------------------------------------------------------ #
    def _init_db(self) -> None:
        try:
            self._db_path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(
                str(self._db_path),
                check_same_thread=False,
                isolation_level=None,
            )
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS ticker_snapshots (
                    ticker TEXT NOT NULL,
                    week_key TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    themes_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (ticker, week_key)
                )
                """
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_snapshots_ticker ON ticker_snapshots(ticker)"
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("MemoryStore SQLite init failed at %s: %s", self._db_path, exc)
            self._conn = None

    def _hydrate_from_db(self) -> None:
        if self._conn is None:
            return
        try:
            for row in self._conn.execute(
                "SELECT ticker, week_key, summary, themes_json, updated_at FROM ticker_snapshots"
            ):
                ticker, week_key, summary, themes_json, updated_at = row
                try:
                    themes = json.loads(themes_json)
                except Exception:  # noqa: BLE001
                    themes = []
                self._ticker_snapshots[ticker.upper()][week_key] = {
                    "summary": summary,
                    "themes": themes,
                    "updated_at": updated_at,
                }
        except Exception as exc:  # noqa: BLE001
            logger.warning("MemoryStore hydrate failed: %s", exc)

    # ------------------------------------------------------------------ #
    # Session memory
    # ------------------------------------------------------------------ #
    def _cleanup(self) -> None:
        now = datetime.now(UTC)
        expired = [key for key, (ts, _) in self._session_data.items() if (now - ts) > self._ttl]
        for key in expired:
            self._session_data.pop(key, None)

    def get_session(self, session_id: str) -> dict[str, Any]:
        with self._lock:
            self._cleanup()
            record = self._session_data.get(session_id)
            if not record:
                return {}
            _, payload = record
            return payload

    def set_session(self, session_id: str, payload: dict[str, Any]) -> None:
        with self._lock:
            self._session_data[session_id] = (datetime.now(UTC), payload)

    # ------------------------------------------------------------------ #
    # Persistent narrative snapshots
    # ------------------------------------------------------------------ #
    def upsert_ticker_snapshot(self, ticker: str, week_key: str, summary: str, themes: list[str]) -> None:
        ticker_upper = ticker.upper()
        updated_at = datetime.now(UTC).isoformat()
        with self._lock:
            self._ticker_snapshots[ticker_upper][week_key] = {
                "summary": summary,
                "themes": themes,
                "updated_at": updated_at,
            }
            if self._conn is not None:
                try:
                    self._conn.execute(
                        """
                        INSERT INTO ticker_snapshots(ticker, week_key, summary, themes_json, updated_at)
                        VALUES (?, ?, ?, ?, ?)
                        ON CONFLICT(ticker, week_key) DO UPDATE SET
                            summary = excluded.summary,
                            themes_json = excluded.themes_json,
                            updated_at = excluded.updated_at
                        """,
                        (ticker_upper, week_key, summary, json.dumps(themes, ensure_ascii=False), updated_at),
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.warning("MemoryStore snapshot persist failed: %s", exc)

    def get_ticker_snapshots(self, ticker: str) -> dict[str, Any]:
        with self._lock:
            return dict(self._ticker_snapshots.get(ticker.upper(), {}))

    def stats(self) -> dict[str, Any]:
        with self._lock:
            total_tickers = len(self._ticker_snapshots)
            total_snapshots = sum(len(weeks) for weeks in self._ticker_snapshots.values())
            return {
                "session_active": len(self._session_data),
                "tickers_with_snapshots": total_tickers,
                "snapshots_total": total_snapshots,
                "persistent_db": str(self._db_path) if self._db_path else "",
            }

    def close(self) -> None:
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception:  # noqa: BLE001
                pass
            self._conn = None
