from __future__ import annotations

import time
from pathlib import Path

from app.jobs import JobRegistry


def test_jobs_persist_across_registry_instances(tmp_path: Path) -> None:
    db_path = tmp_path / "jobs.db"
    jobs_a = JobRegistry(db_path=str(db_path))
    created = jobs_a.create_job("ingest_news", {"ticker": "ASELS"})

    jobs_b = JobRegistry(db_path=str(db_path))
    loaded = jobs_b.get_job(created.job_id)
    assert loaded is not None
    assert loaded.job_type == "ingest_news"
    assert loaded.payload["ticker"] == "ASELS"


def test_async_job_lifecycle(tmp_path: Path) -> None:
    db_path = tmp_path / "jobs.db"
    jobs = JobRegistry(db_path=str(db_path))
    created = jobs.create_job("eval", {"mode": "heuristic"})

    jobs.run_async(created.job_id, lambda: {"ok": True})

    deadline = time.time() + 3
    final = None
    while time.time() < deadline:
        final = jobs.get_job(created.job_id)
        if final and final.status.value in {"completed", "failed"}:
            break
        time.sleep(0.05)

    assert final is not None
    assert final.status.value == "completed"
    assert final.result.get("ok") is True

