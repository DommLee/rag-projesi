from __future__ import annotations

import threading
import uuid
from datetime import UTC, datetime
from typing import Callable

from app.schemas import JobRecord, JobStatus


class JobRegistry:
    def __init__(self) -> None:
        self._jobs: dict[str, JobRecord] = {}
        self._lock = threading.Lock()

    def create_job(self, job_type: str, payload: dict) -> JobRecord:
        job_id = uuid.uuid4().hex[:12]
        record = JobRecord(
            job_id=job_id,
            job_type=job_type,
            status=JobStatus.PENDING,
            created_at=datetime.now(UTC),
            payload=payload,
        )
        with self._lock:
            self._jobs[job_id] = record
        return record

    def list_jobs(self) -> list[JobRecord]:
        with self._lock:
            return sorted(self._jobs.values(), key=lambda x: x.created_at, reverse=True)

    def get_job(self, job_id: str) -> JobRecord | None:
        with self._lock:
            return self._jobs.get(job_id)

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
        with self._lock:
            job = self._jobs[job_id]
            job.status = JobStatus.RUNNING
            job.started_at = datetime.now(UTC)

    def _set_done(self, job_id: str, result: dict) -> None:
        with self._lock:
            job = self._jobs[job_id]
            job.status = JobStatus.COMPLETED
            job.finished_at = datetime.now(UTC)
            job.result = result

    def _set_failed(self, job_id: str, error: str) -> None:
        with self._lock:
            job = self._jobs[job_id]
            job.status = JobStatus.FAILED
            job.finished_at = datetime.now(UTC)
            job.error = error[:4000]

