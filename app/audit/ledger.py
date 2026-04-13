from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import uuid
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def _json_payload(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)


class AnalystAuditLedger:
    def __init__(self, db_path: str = "data/analyst_workspace.db") -> None:
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._init_db()
        self._auto_repair_legacy_chain()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS audit_ledger (
                    event_id TEXT PRIMARY KEY,
                    prev_hash TEXT NOT NULL,
                    record_hash TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    ticker TEXT NOT NULL,
                    asset_scope TEXT NOT NULL,
                    source_key TEXT NOT NULL,
                    payload_sha256 TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    retention_tier TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS analysis_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ticker TEXT NOT NULL,
                    snapshot_key TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(ticker, snapshot_key)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS connector_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_key TEXT NOT NULL,
                    status TEXT NOT NULL,
                    fetched INTEGER NOT NULL DEFAULT 0,
                    inserted INTEGER NOT NULL DEFAULT 0,
                    rejected INTEGER NOT NULL DEFAULT 0,
                    blocked INTEGER NOT NULL DEFAULT 0,
                    retries INTEGER NOT NULL DEFAULT 0,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS ticker_profiles (
                    ticker TEXT PRIMARY KEY,
                    profile_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS chat_sessions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    ticker TEXT NOT NULL,
                    message TEXT NOT NULL,
                    response_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS upload_events (
                    upload_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    ticker TEXT NOT NULL,
                    retained_path TEXT NOT NULL,
                    content_type TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS audit_repairs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    reason TEXT NOT NULL,
                    repaired_rows INTEGER NOT NULL DEFAULT 0,
                    broken_at TEXT NOT NULL DEFAULT "",
                    before_last_hash TEXT NOT NULL DEFAULT "",
                    after_last_hash TEXT NOT NULL DEFAULT "",
                    details_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_ledger_ticker ON audit_ledger(ticker, created_at DESC)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_ledger_source ON audit_ledger(source_key, created_at DESC)")

    @staticmethod
    def _sha256(text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    def append_event(
        self,
        *,
        event_type: str,
        payload: Any,
        ticker: str = "",
        asset_scope: str = "bist",
        source_key: str = "",
        session_id: str = "",
        actor: str = "system",
        retention_tier: str = "permanent",
    ) -> dict[str, str]:
        normalized_payload = _json_payload(payload)
        payload_sha = self._sha256(normalized_payload)
        created_at = datetime.now(UTC).isoformat()
        event_id = str(uuid.uuid4())
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT record_hash FROM audit_ledger ORDER BY created_at DESC, rowid DESC LIMIT 1"
            ).fetchone()
            prev_hash = row["record_hash"] if row else "GENESIS"
            material = "|".join(
                [
                    prev_hash,
                    event_type,
                    ticker.upper(),
                    asset_scope,
                    source_key,
                    payload_sha,
                    session_id,
                    actor,
                    retention_tier,
                    created_at,
                ]
            )
            record_hash = self._sha256(material)
            conn.execute(
                """
                INSERT INTO audit_ledger (
                    event_id, prev_hash, record_hash, event_type, ticker, asset_scope,
                    source_key, payload_sha256, payload_json, session_id, actor, retention_tier, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event_id,
                    prev_hash,
                    record_hash,
                    event_type,
                    ticker.upper(),
                    asset_scope,
                    source_key,
                    payload_sha,
                    normalized_payload,
                    session_id,
                    actor,
                    retention_tier,
                    created_at,
                ),
            )
        return {"event_id": event_id, "record_hash": record_hash, "created_at": created_at}

    def recent_events(self, ticker: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        query = "SELECT * FROM audit_ledger"
        params: list[Any] = []
        if ticker:
            query += " WHERE ticker=?"
            params.append(ticker.upper())
        query += " ORDER BY created_at DESC, rowid DESC LIMIT ?"
        params.append(max(1, min(limit, 1000)))
        with self._connect() as conn:
            rows = conn.execute(query, tuple(params)).fetchall()
        return [dict(row) for row in rows]

    def _chain_stats(self) -> dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT COUNT(*) AS repair_count, MAX(created_at) AS last_repair_at
                FROM audit_repairs
                """
            ).fetchone()
        return {
            "repair_count": int(row["repair_count"] or 0) if row else 0,
            "last_repair_at": row["last_repair_at"] if row else None,
        }

    def _scan_chain(self) -> dict[str, Any]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM audit_ledger ORDER BY created_at ASC, rowid ASC").fetchall()
        prev_hash = "GENESIS"
        for index, row in enumerate(rows):
            material = "|".join(
                [
                    prev_hash,
                    row["event_type"],
                    row["ticker"],
                    row["asset_scope"],
                    row["source_key"],
                    row["payload_sha256"],
                    row["session_id"],
                    row["actor"],
                    row["retention_tier"],
                    row["created_at"],
                ]
            )
            expected_hash = self._sha256(material)
            if row["prev_hash"] != prev_hash or row["record_hash"] != expected_hash:
                return {
                    "ok": False,
                    "global_count": len(rows),
                    "broken_at": row["event_id"],
                    "position": index,
                    "expected_prev_hash": prev_hash,
                    "expected_hash": expected_hash,
                }
            prev_hash = row["record_hash"]
        return {
            "ok": True,
            "global_count": len(rows),
            "broken_at": None,
            "last_hash": prev_hash if rows else "GENESIS",
        }

    def _auto_repair_legacy_chain(self) -> None:
        status = self._scan_chain()
        if status["ok"]:
            return
        self.repair_chain(reason="legacy_chain_migration")

    def repair_chain(self, reason: str = "manual_repair") -> dict[str, Any]:
        with self._lock, self._connect() as conn:
            rows = conn.execute("SELECT rowid, * FROM audit_ledger ORDER BY created_at ASC, rowid ASC").fetchall()
            prev_hash = "GENESIS"
            updates: list[tuple[str, str, int]] = []
            broken_at = ""
            before_last_hash = rows[-1]["record_hash"] if rows else "GENESIS"
            for row in rows:
                material = "|".join(
                    [
                        prev_hash,
                        row["event_type"],
                        row["ticker"],
                        row["asset_scope"],
                        row["source_key"],
                        row["payload_sha256"],
                        row["session_id"],
                        row["actor"],
                        row["retention_tier"],
                        row["created_at"],
                    ]
                )
                expected_hash = self._sha256(material)
                if not broken_at and (row["prev_hash"] != prev_hash or row["record_hash"] != expected_hash):
                    broken_at = row["event_id"]
                if row["prev_hash"] != prev_hash or row["record_hash"] != expected_hash:
                    updates.append((prev_hash, expected_hash, row["rowid"]))
                prev_hash = expected_hash

            if updates:
                conn.executemany(
                    "UPDATE audit_ledger SET prev_hash=?, record_hash=? WHERE rowid=?",
                    updates,
                )
            created_at = datetime.now(UTC).isoformat()
            details = {
                "reason": reason,
                "repaired_rows": len(updates),
                "broken_at": broken_at,
                "rowids": [rowid for _, _, rowid in updates[:50]],
            }
            conn.execute(
                """
                INSERT INTO audit_repairs (
                    reason, repaired_rows, broken_at, before_last_hash, after_last_hash, details_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    reason,
                    len(updates),
                    broken_at,
                    before_last_hash,
                    prev_hash if rows else "GENESIS",
                    _json_payload(details),
                    created_at,
                ),
            )
        return {
            "ok": True,
            "reason": reason,
            "repaired_rows": len(updates),
            "broken_at": broken_at or None,
            "after_last_hash": prev_hash if rows else "GENESIS",
            "created_at": created_at,
        }

    def list_repairs(self, limit: int = 20) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM audit_repairs ORDER BY created_at DESC, id DESC LIMIT ?",
                (max(1, min(limit, 200)),),
            ).fetchall()
        return [
            {
                "id": row["id"],
                "reason": row["reason"],
                "repaired_rows": row["repaired_rows"],
                "broken_at": row["broken_at"] or None,
                "before_last_hash": row["before_last_hash"],
                "after_last_hash": row["after_last_hash"],
                "details": json.loads(row["details_json"]),
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    def verify_chain(self, ticker: str | None = None) -> dict[str, Any]:
        status = self._scan_chain()
        chain_stats = self._chain_stats()
        ticker_upper = ticker.upper() if ticker else None
        scoped_count = 0
        scoped_last_hash = "GENESIS"
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT ticker, event_id, event_type, source_key, asset_scope, created_at, record_hash
                FROM audit_ledger
                ORDER BY created_at ASC, rowid ASC
                """
            ).fetchall()
        scoped_rows = []
        for row in rows:
            if not ticker_upper or row["ticker"] == ticker_upper:
                scoped_count += 1
                scoped_last_hash = row["record_hash"]
                scoped_rows.append(row)
        event_type_counts = dict(Counter(row["event_type"] for row in scoped_rows))
        source_key_counts = dict(Counter(row["source_key"] for row in scoped_rows))
        asset_scope_counts = dict(Counter(row["asset_scope"] for row in scoped_rows))
        ticker_breakdown = dict(Counter(row["ticker"] for row in scoped_rows))
        head_preview = [
            {
                "event_id": row["event_id"],
                "ticker": row["ticker"],
                "event_type": row["event_type"],
                "source_key": row["source_key"],
                "asset_scope": row["asset_scope"],
                "created_at": row["created_at"],
            }
            for row in scoped_rows[:3]
        ]
        tail_preview = [
            {
                "event_id": row["event_id"],
                "ticker": row["ticker"],
                "event_type": row["event_type"],
                "source_key": row["source_key"],
                "asset_scope": row["asset_scope"],
                "created_at": row["created_at"],
            }
            for row in scoped_rows[-3:]
        ]
        first_event = scoped_rows[0] if scoped_rows else None
        last_event = scoped_rows[-1] if scoped_rows else None
        if not status["ok"]:
            return {
                "ok": False,
                "count": scoped_count if ticker_upper else status["global_count"],
                "global_count": status["global_count"],
                "broken_at": status["broken_at"],
                "position": status["position"],
                "repair_count": chain_stats["repair_count"],
                "last_repair_at": chain_stats["last_repair_at"],
                "first_event_at": first_event["created_at"] if first_event else None,
                "last_event_at": last_event["created_at"] if last_event else None,
                "first_event_id": first_event["event_id"] if first_event else None,
                "last_event_id": last_event["event_id"] if last_event else None,
                "event_type_counts": event_type_counts,
                "source_key_counts": source_key_counts,
                "asset_scope_counts": asset_scope_counts,
                "ticker_breakdown": ticker_breakdown,
                "head_preview": head_preview,
                "tail_preview": tail_preview,
            }
        return {
            "ok": True,
            "count": scoped_count if ticker_upper else status["global_count"],
            "global_count": status["global_count"],
            "broken_at": None,
            "last_hash": scoped_last_hash if ticker_upper else status["last_hash"],
            "repair_count": chain_stats["repair_count"],
            "last_repair_at": chain_stats["last_repair_at"],
            "first_event_at": first_event["created_at"] if first_event else None,
            "last_event_at": last_event["created_at"] if last_event else None,
            "first_event_id": first_event["event_id"] if first_event else None,
            "last_event_id": last_event["event_id"] if last_event else None,
            "event_type_counts": event_type_counts,
            "source_key_counts": source_key_counts,
            "asset_scope_counts": asset_scope_counts,
            "ticker_breakdown": ticker_breakdown,
            "head_preview": head_preview,
            "tail_preview": tail_preview,
        }

    def save_analysis_snapshot(self, ticker: str, snapshot_key: str, summary: str, payload: Any) -> None:
        created_at = datetime.now(UTC).isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO analysis_snapshots (ticker, snapshot_key, summary, payload_json, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (ticker.upper(), snapshot_key, summary, _json_payload(payload), created_at),
            )

    def latest_analysis_snapshot(self, ticker: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM analysis_snapshots WHERE ticker=? ORDER BY created_at DESC, id DESC LIMIT 1",
                (ticker.upper(),),
            ).fetchone()
        if not row:
            return None
        return {
            "ticker": row["ticker"],
            "snapshot_key": row["snapshot_key"],
            "summary": row["summary"],
            "payload": json.loads(row["payload_json"]),
            "created_at": row["created_at"],
        }

    def save_ticker_profile(self, ticker: str, profile: Any) -> None:
        updated_at = datetime.now(UTC).isoformat()
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO ticker_profiles (ticker, profile_json, updated_at) VALUES (?, ?, ?)",
                (ticker.upper(), _json_payload(profile), updated_at),
            )

    def get_ticker_profile(self, ticker: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM ticker_profiles WHERE ticker=?", (ticker.upper(),)).fetchone()
        if not row:
            return None
        return {"ticker": row["ticker"], "profile": json.loads(row["profile_json"]), "updated_at": row["updated_at"]}

    def log_connector_run(self, source_key: str, payload: Any) -> None:
        created_at = datetime.now(UTC).isoformat()
        data = payload if isinstance(payload, dict) else {"payload": payload}
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO connector_runs (source_key, status, fetched, inserted, rejected, blocked, retries, payload_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    source_key,
                    str(data.get("status", "unknown")),
                    int(data.get("fetched", 0)),
                    int(data.get("inserted", data.get("inserted_chunks", 0))),
                    int(data.get("rejected_entity", 0)),
                    int(data.get("blocked", 0)),
                    int(data.get("retries", 0)),
                    _json_payload(data),
                    created_at,
                ),
            )

    def record_chat_session(self, session_id: str, ticker: str, message: str, response: Any) -> None:
        created_at = datetime.now(UTC).isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO chat_sessions (session_id, ticker, message, response_json, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (session_id, ticker.upper(), message, _json_payload(response), created_at),
            )

    def record_upload_event(
        self,
        *,
        upload_id: str,
        session_id: str,
        ticker: str,
        retained_path: str,
        content_type: str,
        payload: Any,
    ) -> None:
        created_at = datetime.now(UTC).isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO upload_events (upload_id, session_id, ticker, retained_path, content_type, payload_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    upload_id,
                    session_id,
                    ticker.upper(),
                    retained_path,
                    content_type,
                    _json_payload(payload),
                    created_at,
                ),
            )

    def recent_chat_sessions(self, ticker: str | None = None, session_id: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
        query = "SELECT * FROM chat_sessions"
        params: list[Any] = []
        conditions = []
        if ticker:
            conditions.append("ticker=?")
            params.append(ticker.upper())
        if session_id:
            conditions.append("session_id=?")
            params.append(session_id)
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        query += " ORDER BY created_at DESC, id DESC LIMIT ?"
        params.append(max(1, min(limit, 200)))
        with self._connect() as conn:
            rows = conn.execute(query, tuple(params)).fetchall()
        return [
            {
                "session_id": row["session_id"],
                "ticker": row["ticker"],
                "message": row["message"],
                "response": json.loads(row["response_json"]),
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    def recent_upload_events(self, ticker: str | None = None, session_id: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
        query = "SELECT * FROM upload_events"
        params: list[Any] = []
        conditions = []
        if ticker:
            conditions.append("ticker=?")
            params.append(ticker.upper())
        if session_id:
            conditions.append("session_id=?")
            params.append(session_id)
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(max(1, min(limit, 200)))
        with self._connect() as conn:
            rows = conn.execute(query, tuple(params)).fetchall()
        return [
            {
                "upload_id": row["upload_id"],
                "session_id": row["session_id"],
                "ticker": row["ticker"],
                "retained_path": row["retained_path"],
                "content_type": row["content_type"],
                "payload": json.loads(row["payload_json"]),
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    def recent_connector_runs(self, source_key: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
        query = "SELECT * FROM connector_runs"
        params: list[Any] = []
        if source_key:
            query += " WHERE source_key=?"
            params.append(source_key)
        query += " ORDER BY created_at DESC, id DESC LIMIT ?"
        params.append(max(1, min(limit, 200)))
        with self._connect() as conn:
            rows = conn.execute(query, tuple(params)).fetchall()
        return [
            {
                "source_key": row["source_key"],
                "status": row["status"],
                "fetched": row["fetched"],
                "inserted": row["inserted"],
                "rejected": row["rejected"],
                "blocked": row["blocked"],
                "retries": row["retries"],
                "payload": json.loads(row["payload_json"]),
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    def audit_summary(self, ticker: str | None = None) -> dict[str, Any]:
        rows = self.recent_events(ticker=ticker, limit=50)
        verify = self.verify_chain(ticker=ticker)
        return {
            "event_count": verify["count"],
            "chain_ok": verify["ok"],
            "last_event_at": rows[0]["created_at"] if rows else None,
            "last_event_type": rows[0]["event_type"] if rows else None,
            "repair_count": verify.get("repair_count", 0),
            "last_repair_at": verify.get("last_repair_at"),
            "first_event_at": verify.get("first_event_at"),
            "event_type_counts": verify.get("event_type_counts", {}),
            "source_key_counts": verify.get("source_key_counts", {}),
            "asset_scope_counts": verify.get("asset_scope_counts", {}),
        }
