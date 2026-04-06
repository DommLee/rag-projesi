from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any

from app.config import get_settings


class MemoryStore:
    """
    Mem0-style lightweight tiers:
    1. Session memory with TTL.
    2. Ticker narrative weekly snapshots.
    3. Evidence memory as immutable claim hashes (handled by ClaimLedger).
    """

    def __init__(self) -> None:
        self._session_data: dict[str, tuple[datetime, dict[str, Any]]] = {}
        self._ticker_snapshots: dict[str, dict[str, Any]] = defaultdict(dict)
        self._ttl = timedelta(hours=get_settings().session_ttl_hours)

    def _cleanup(self) -> None:
        now = datetime.now(UTC)
        expired = [key for key, (ts, _) in self._session_data.items() if (now - ts) > self._ttl]
        for key in expired:
            self._session_data.pop(key, None)

    def get_session(self, session_id: str) -> dict[str, Any]:
        self._cleanup()
        record = self._session_data.get(session_id)
        if not record:
            return {}
        _, payload = record
        return payload

    def set_session(self, session_id: str, payload: dict[str, Any]) -> None:
        self._session_data[session_id] = (datetime.now(UTC), payload)

    def upsert_ticker_snapshot(self, ticker: str, week_key: str, summary: str, themes: list[str]) -> None:
        self._ticker_snapshots[ticker.upper()][week_key] = {
            "summary": summary,
            "themes": themes,
            "updated_at": datetime.now(UTC).isoformat(),
        }

    def get_ticker_snapshots(self, ticker: str) -> dict[str, Any]:
        return self._ticker_snapshots.get(ticker.upper(), {})

