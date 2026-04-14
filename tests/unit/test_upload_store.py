from __future__ import annotations

import base64

import pytest

from app.uploads.store import UploadStore


def _payload(text: str) -> str:
    return base64.b64encode(text.encode("utf-8")).decode("utf-8")


def test_upload_store_rejects_office_lock_files(tmp_path) -> None:
    store = UploadStore(str(tmp_path / "uploads"), str(tmp_path / "index.json"))

    with pytest.raises(ValueError, match="temporary_office_lock_file"):
        store.save_upload(
            session_id="s1",
            filename="~$G_Assignment_v2 (5).docx",
            ticker="ASELS",
            content_base64=_payload("ASELS"),
            content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )


def test_upload_store_rejects_unsupported_docx(tmp_path) -> None:
    store = UploadStore(str(tmp_path / "uploads"), str(tmp_path / "index.json"))

    with pytest.raises(ValueError, match="unsupported_upload_file_type:.docx"):
        store.save_upload(
            session_id="s1",
            filename="report.docx",
            ticker="ASELS",
            content_base64=_payload("ASELS raporu"),
            content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )


def test_upload_store_accepts_markdown(tmp_path) -> None:
    store = UploadStore(str(tmp_path / "uploads"), str(tmp_path / "index.json"))

    record, chunks = store.save_upload(
        session_id="s1",
        filename="asels-analyst-report.md",
        ticker="ASELS",
        content_base64=_payload("# ASELS Analyst Report\n\nASELS icin resmi kaynak analizi."),
        content_type="text/markdown",
    )

    assert record.filename == "asels-analyst-report.md"
    assert record.detected_ticker == "ASELS"
    assert chunks


def test_upload_store_hides_legacy_unsupported_records(tmp_path) -> None:
    store = UploadStore(str(tmp_path / "uploads"), str(tmp_path / "index.json"))
    store.save_upload(
        session_id="s1",
        filename="asels-analyst-report.md",
        ticker="ASELS",
        content_base64=_payload("# ASELS Analyst Report"),
        content_type="text/markdown",
    )
    rows = store._load_index()
    legacy_bad = dict(rows[0])
    legacy_bad["upload_id"] = "bad"
    legacy_bad["filename"] = "~$G_Assignment_v2 (5).docx"
    rows.append(legacy_bad)
    store._save_index(rows)

    visible = store.list_session("s1")

    assert [row.filename for row in visible] == ["asels-analyst-report.md"]
