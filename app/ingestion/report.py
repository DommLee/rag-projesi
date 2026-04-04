from __future__ import annotations

import logging
import os
import re
import tempfile
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
from app.utils.dates import parse_date

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
    def __init__(self) -> None:
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "bist-agentic-rag/1.0"})
        self.policy = LegalSafeCrawlerPolicy()

    def _download_pdf(self, url: str) -> str:
        decision = self.policy.decide(url)
        if not decision.allowed:
            raise RuntimeError(f"Blocked by crawling policy: {decision.reason} ({url})")
        self.policy.wait_rate_limit(url)
        parsed = urlparse(url)
        ext = Path(parsed.path).suffix or ".pdf"
        handle, tmp_path = tempfile.mkstemp(suffix=ext)
        os.close(handle)
        response = self.session.get(url, timeout=30)
        response.raise_for_status()
        with open(tmp_path, "wb") as file_obj:
            file_obj.write(response.content)
        return tmp_path

    @staticmethod
    def _extract_metadata(text: str, source_url: str, institution: str) -> tuple[str, datetime | None]:
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        title = lines[0][:220] if lines else f"Broker Report - {Path(source_url).name}"

        date_match = re.search(r"(\d{2}[./-]\d{2}[./-]\d{4})", text)
        if date_match:
            try:
                parsed = parse_date(date_match.group(1))
                return title, parsed
            except Exception:  # noqa: BLE001
                pass
        month_match = re.search(
            r"(Ocak|Subat|Şubat|Mart|Nisan|Mayis|Mayıs|Haziran|Temmuz|Agustos|Ağustos|Eylul|Eylül|Ekim|Kasim|Kasım|Aralik|Aralık)\s+\d{4}",
            text,
            flags=re.IGNORECASE,
        )
        if month_match:
            try:
                parsed = parse_date(month_match.group(0))
                return title, parsed
            except Exception:  # noqa: BLE001
                pass
        return title, None

    def collect(
        self,
        ticker: str,
        institution: str,
        source_urls: list[str],
        date_from: datetime | None = None,
        date_to: datetime | None = None,
    ) -> list[DocumentChunk]:
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

                now = datetime.utcnow()
                title, parsed_date = self._extract_metadata(text=text, source_url=src, institution=institution)
                published_date = parsed_date or now
                confidence = 0.85 if parsed_date else 0.62
                raw = RawDoc(
                    ticker=ticker,
                    source_type=SourceType.BROKER_REPORT,
                    institution=institution,
                    url=src,
                    title=title,
                    text=text,
                    date=published_date,
                    published_at=published_date,
                    retrieved_at=now,
                    language="tr",
                    confidence=confidence,
                )
                if date_from and parse_date(raw.date) < date_from:
                    continue
                if date_to and parse_date(raw.date) > date_to:
                    continue
                chunks.extend(build_chunks(raw))
            except Exception as exc:  # noqa: BLE001
                logger.warning("Report ingestion failed for %s: %s", src, exc)
            finally:
                if downloaded and os.path.exists(local_path):
                    os.remove(local_path)
        return chunks
