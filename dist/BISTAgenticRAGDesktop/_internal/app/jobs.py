from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable

from app.config import get_settings
from app.schemas import JobRecord, JobStatus


class JobRegistry:
    def __init__(self, db_path: str | None = None) -> None:
        self.db_path = db_path or get_settings().jobs_db_path
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
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
                CREATE TABLE IF NOT EXISTS jobs (
                    job_id TEXT PRIMARY KEY,
                    job_type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    started_at TEXT,
                    finished_at TEXT,
                    payload_json TEXT NOT NULL,
                    result_json TEXT NOT NULL,
                    error TEXT
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_created_at ON jobs(created_at)")

    @staticmethod
    def _to_iso(value: datetime | None) -> str | None:
        return value.isoformat() if value else None

    @staticmethod
    def _parse_dt(value: str | None) -> datetime | None:
        if not value:
            return None
        return datetime.fromisoformat(value)

    @staticmethod
    def _row_to_record(row: sqlite3.Row) -> JobRecord:
        return JobRecord(
            job_id=row["job_id"],
            job_type=row["job_type"],
            status=JobStatus(row["status"]),
            created_at=datetime.fromisoformat(row["created_at"]),
            started_at=JobRegistry._parse_dt(row["started_at"]),
            finished_at=JobRegistry._parse_dt(row["finished_at"]),
            payload=json.loads(row["payload_json"] or "{}"),
            result=json.loads(row["result_json"] or "{}"),
            error=row["error"],
        )

    def create_job(self, job_type: str, payload: dict) -> JobRecord:
        job_id = uuid.uuid4().hex[:12]
        record = JobRecord(
            job_id=job_id,
            job_type=job_type,
            status=JobStatus.PENDING,
            created_at=datetime.now(UTC),
            payload=payload,
        )
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO jobs (
                    job_id, job_type, status, created_at, started_at, finished_at,
                    payload_json, result_json, error
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.job_id,
                    record.job_type,
                    record.status.value,
                    self._to_iso(record.created_at),
                    None,
                    None,
                    json.dumps(record.payload, ensure_ascii=False),
                    "{}",
                    None,
                ),
            )
        return record

    def list_jobs(self) -> list[JobRecord]:
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM jobs ORDER BY datetime(created_at) DESC LIMIT 500"
            ).fetchall()
        return [self._row_to_record(row) for row in rows]

    def get_job(self, job_id: str) -> JobRecord | None:
        with self._lock, self._connect() as conn:
            row = conn.execute("SELECT * FROM jobs WHERE job_id=?", (job_id,)).fetchone()
        return self._row_to_record(row) if row else None

    def run_async(self, job_id: str, runner: Callable[[], dict]) -> None:
        def _target() -> None:
            self._set_running(job_id)
            try:
                result = runner()
                self._set_done(job_id, result)
            except Exception as exc:  # noqa: BLE001
                self._set_failed(job_id, str(exc))

        thread = threading.Thread(target=_target, daemon=True)
        thread.start()

    def _set_running(self, job_id: str) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                "UPDATE jobs SET status=?, started_at=? WHERE job_id=?",
                (JobStatus.RUNNING.value, self._to_iso(datetime.now(UTC)), job_id),
            )

    def _set_done(self, job_id: str, result: dict) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                "UPDATE jobs SET status=?, finished_at=?, result_json=? WHERE job_id=?",
                (
                    JobStatus.COMPLETED.value,
                    self._to_iso(datetime.now(UTC)),
                    json.dumps(result, ensure_ascii=False),
                    job_id,
                ),
            )

    def _set_failed(self, job_id: str, error: str) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                "UPDATE jobs SET status=?, finished_at=?, error=? WHERE job_id=?",
                (
                    JobStatus.FAILED.value,
                    self._to_iso(datetime.now(UTC)),
                    error[:4000],
                    job_id,
                ),
            )

