from __future__ import annotations

import logging
import os
import re
import tempfile
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

import requests

try:
    from pypdf import PdfReader
except Exception:  # noqa: BLE001
    PdfReader = None

from app.ingestion.base import BaseIngestor
from app.ingestion.chunking import RawDoc, build_chunks
from app.ingestion.policy import LegalSafeCrawlerPolicy
from app.schemas import DocumentChunk, SourceType
from app.utils.dates import now_utc, parse_date

logger = logging.getLogger(__name__)


def _extract_pdf_text(path: str) -> str:
    if PdfReader is None:
        raise RuntimeError("pypdf is not installed")
    reader = PdfReader(path)
    pages = []
    for page in reader.pages:
        pages.append(page.extract_text() or "")
    return "\n".join(pages).strip()


def _ocr_pdf_text(path: str) -> str:
    try:
        from pdf2image import convert_from_path
        import pytesseract
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"OCR dependencies missing: {exc}") from exc

    text_parts = []
    images = convert_from_path(path, dpi=220)
    for image in images:
        text_parts.append(pytesseract.image_to_string(image, lang="tur+eng"))
    return "\n".join(text_parts).strip()


class ReportIngestor(BaseIngestor):
    def __init__(self, max_retries: int = 3) -> None:
        self.max_retries = max_retries
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "BIST-Agentic-RAG/2.0 (Academic Research Use)"})
        self.policy = LegalSafeCrawlerPolicy()
        self.last_policy_summary: dict[str, int | bool] = {
            "policy_applied": True,
            "blocked_count": 0,
            "retry_count": 0,
            "fetched_count": 0,
            "success_count": 0,
            "last_success_at": "",
            "blocked_reason_counts": {},
        }

    def _download_pdf(self, url: str) -> str:
        decision = self.policy.decide(url)
        if not decision.allowed:
            self.last_policy_summary["blocked_count"] = int(self.last_policy_summary["blocked_count"]) + 1
            reasons = dict(self.last_policy_summary.get("blocked_reason_counts", {}))
            reasons[decision.reason] = int(reasons.get(decision.reason, 0)) + 1
            self.last_policy_summary["blocked_reason_counts"] = reasons
            raise RuntimeError(f"Blocked by crawling policy: {decision.reason} ({url})")
        self.policy.wait_rate_limit(url)
        parsed = urlparse(url)
        ext = Path(parsed.path).suffix or ".pdf"
        handle, tmp_path = tempfile.mkstemp(suffix=ext)
        os.close(handle)

        last_exc: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            try:
                response = self.session.get(url, timeout=30)
                response.raise_for_status()
                with open(tmp_path, "wb") as file_obj:
                    file_obj.write(response.content)
                self.last_policy_summary["fetched_count"] = int(self.last_policy_summary["fetched_count"]) + 1
                return tmp_path
            except Exception as exc:  # noqa: BLE001
                self.last_policy_summary["retry_count"] = int(self.last_policy_summary["retry_count"]) + 1
                last_exc = exc
                time.sleep(0.5 * attempt)
        if last_exc:
            raise last_exc
        raise RuntimeError(f"Failed to download report: {url}")

    @staticmethod
    def _extract_metadata(text: str, source_url: str, institution: str) -> tuple[str, datetime | None, bool]:
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        title = lines[0][:220] if lines else f"Broker Report - {Path(source_url).name}"
        _ = institution

        date_match = re.search(r"(\d{2}[./-]\d{2}[./-]\d{4})", text)
        if date_match:
            try:
                parsed = parse_date(date_match.group(1))
                return title, parsed, True
            except Exception:  # noqa: BLE001
                pass

        month_match = re.search(
            r"(Ocak|Şubat|Mart|Nisan|Mayıs|Haziran|Temmuz|Ağustos|Eylül|Ekim|Kasım|Aralık)\s+\d{4}",
            text,
            flags=re.IGNORECASE,
        )
        if month_match:
            try:
                parsed = parse_date(month_match.group(0))
                return title, parsed, True
            except Exception:  # noqa: BLE001
                pass
        return title, None, False

    def collect(
        self,
        ticker: str,
        institution: str,
        source_urls: list[str],
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        notification_types: list[str] | None = None,
    ) -> list[DocumentChunk]:
        _ = notification_types
        self.last_policy_summary = {
            "policy_applied": True,
            "blocked_count": 0,
            "retry_count": 0,
            "fetched_count": 0,
            "success_count": 0,
            "last_success_at": "",
            "blocked_reason_counts": {},
        }
        chunks: list[DocumentChunk] = []
        for src in source_urls:
            local_path = src
            downloaded = False
            try:
                if src.lower().startswith("http"):
                    local_path = self._download_pdf(src)
                    downloaded = True

                text = _extract_pdf_text(local_path)
                if len(text.strip()) < 200:
                    text = _ocr_pdf_text(local_path)
                if not text.strip():
                    logger.warning("Report text extraction empty: %s", src)
                    continue

                now = now_utc()
                title, parsed_date, has_date_metadata = self._extract_metadata(
                    text=text, source_url=src, institution=institution
                )
                published_date = parsed_date or now
                confidence = 0.87 if has_date_metadata else 0.55
                raw = RawDoc(
                    ticker=ticker,
                    source_type=SourceType.BROKERAGE,
                    institution=institution,
                    url=src,
                    title=title,
                    text=text,
                    date=published_date,
                    published_at=published_date,
                    retrieved_at=now,
                    notification_type="Financial Report",
                    language="tr",
                    confidence=confidence,
                )
                built_chunks = build_chunks(raw)
                if not has_date_metadata:
                    for chunk in built_chunks:
                        chunk.metadata["evidence_gaps"] = ["report_metadata_missing_date"]
                        chunk.metadata["metadata_confidence"] = confidence

                if date_from and parse_date(raw.date) < date_from:
                    continue
                if date_to and parse_date(raw.date) > date_to:
                    continue
                chunks.extend(built_chunks)
                if built_chunks:
                    self.last_policy_summary["success_count"] = int(self.last_policy_summary["success_count"]) + 1
            except Exception as exc:  # noqa: BLE001
                logger.warning("Report ingestion failed for %s: %s", src, exc)
            finally:
                if downloaded and os.path.exists(local_path):
                    os.remove(local_path)
        if chunks:
            self.last_policy_summary["last_success_at"] = now_utc().isoformat()
        return chunks
