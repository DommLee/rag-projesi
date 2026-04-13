from __future__ import annotations

import base64
import json
import tempfile
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup

from app.ingestion.chunking import RawDoc, build_chunks
from app.ingestion.report import _extract_pdf_text, _ocr_pdf_text
from app.market.entity_aliases import detect_ticker_from_text
from app.schemas import DocumentChunk, SourceType, UploadRecord
from app.utils.dates import now_utc
from app.utils.text import normalize_visible_text, repair_mojibake


class UploadStore:
    def __init__(self, root_dir: str, index_path: str) -> None:
        self.root_dir = Path(root_dir)
        self.index_path = Path(index_path)
        self.root_dir.mkdir(parents=True, exist_ok=True)
        self.index_path.parent.mkdir(parents=True, exist_ok=True)

    def _load_index(self) -> list[dict[str, Any]]:
        if not self.index_path.exists():
            return []
        try:
            return json.loads(self.index_path.read_text(encoding="utf-8"))
        except Exception:
            return []

    def _save_index(self, rows: list[dict[str, Any]]) -> None:
        self.index_path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")

    def list_session(self, session_id: str) -> list[UploadRecord]:
        rows = self._load_index()
        out = []
        for row in rows:
            if row.get("session_id") == session_id:
                try:
                    out.append(UploadRecord.model_validate(row))
                except Exception:
                    continue
        out.sort(key=lambda row: row.created_at, reverse=True)
        return out

    @staticmethod
    def _decode_content(payload_base64: str) -> bytes:
        return base64.b64decode(payload_base64.encode("utf-8"))

    @staticmethod
    def _parse_plain_bytes(filename: str, content_type: str, raw: bytes) -> tuple[str, int, list[str]]:
        ext = Path(filename).suffix.lower()
        warnings: list[str] = []
        if ext in {".json"} or "json" in content_type:
            try:
                parsed = json.loads(raw.decode("utf-8-sig"))
                text = json.dumps(parsed, ensure_ascii=False, indent=2)
                return text, 1, warnings
            except Exception:
                warnings.append("json_parse_failed_fallback_text")
        decoded = raw.decode("utf-8-sig", errors="ignore")
        if ext in {".html", ".htm"} or "html" in content_type:
            decoded = BeautifulSoup(decoded, "lxml").get_text(" ", strip=True)
        return repair_mojibake(normalize_visible_text(decoded)), max(1, decoded.count("\n") // 40 + 1), warnings

    @staticmethod
    def _parse_pdf(path: Path) -> tuple[str, int, list[str]]:
        warnings: list[str] = []
        try:
            text = _extract_pdf_text(str(path))
        except Exception as exc:
            warnings.append(f"pdf_extract_failed:{exc}")
            text = ""
        if len(text.strip()) < 200:
            try:
                ocr_text = _ocr_pdf_text(str(path))
                if ocr_text.strip():
                    text = ocr_text
                    warnings.append("ocr_fallback_used")
            except Exception as exc:
                warnings.append(f"pdf_ocr_failed:{exc}")
        page_estimate = max(1, text.count("\n\f") + 1)
        return normalize_visible_text(text), page_estimate, warnings

    def save_upload(
        self,
        *,
        session_id: str,
        filename: str,
        ticker: str = "",
        content_base64: str = "",
        source_path: str = "",
        content_type: str = "",
    ) -> tuple[UploadRecord, list[DocumentChunk]]:
        if not filename and source_path:
            filename = Path(source_path).name
        if not filename:
            raise ValueError("filename_required")

        upload_id = uuid.uuid4().hex
        session_dir = self.root_dir / session_id
        session_dir.mkdir(parents=True, exist_ok=True)
        stored_path = session_dir / f"{upload_id}_{filename}"

        if source_path:
            raw_bytes = Path(source_path).read_bytes()
        elif content_base64:
            raw_bytes = self._decode_content(content_base64)
        else:
            raise ValueError("upload_content_missing")

        stored_path.write_bytes(raw_bytes)

        ext = stored_path.suffix.lower()
        warnings: list[str] = []
        parsed_pages = 1
        if ext == ".pdf" or "pdf" in content_type:
            text, parsed_pages, warnings = self._parse_pdf(stored_path)
        else:
            text, parsed_pages, warnings = self._parse_plain_bytes(filename, content_type, raw_bytes)

        text = normalize_visible_text(text)
        detected_ticker = ticker.strip().upper() or detect_ticker_from_text(text)
        final_ticker = detected_ticker or "GENERIC"
        now = now_utc()
        raw_doc = RawDoc(
            ticker=final_ticker,
            source_type=SourceType.USER_UPLOAD,
            institution="User Upload",
            url=f"user-upload://{upload_id}/{filename}",
            title=filename,
            text=text or filename,
            date=now,
            published_at=now,
            retrieved_at=now.isoformat(),
            notification_type="General Assembly",
            language="tr",
            confidence=0.78 if detected_ticker else 0.62,
            metadata={
                "source_channel": "user",
                "source_reliability": 0.65,
                "raw_doc_path": str(stored_path),
                "analysis_cache_key": f"{final_ticker}:{upload_id}",
                "session_id": session_id,
                "upload_id": upload_id,
                "entity_aliases": [final_ticker] if final_ticker and final_ticker != "GENERIC" else [],
                "discovered_via": "user_upload",
            },
        )
        chunks = build_chunks(raw_doc)
        record = UploadRecord(
            upload_id=upload_id,
            session_id=session_id,
            filename=filename,
            stored_path=str(stored_path),
            content_type=content_type,
            ticker=ticker.strip().upper(),
            detected_ticker=detected_ticker,
            inserted_chunks=0,
            parsed_pages=parsed_pages,
            warnings=warnings,
            created_at=datetime.now(UTC),
            source_type=SourceType.USER_UPLOAD,
        )
        rows = self._load_index()
        rows.append(record.model_dump(mode="json"))
        self._save_index(rows)
        return record, chunks

    def update_record(self, upload_id: str, **updates: Any) -> None:
        rows = self._load_index()
        changed = False
        for row in rows:
            if row.get("upload_id") == upload_id:
                row.update(updates)
                changed = True
                break
        if changed:
            self._save_index(rows)
