from __future__ import annotations

import logging
import time
from datetime import datetime
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from app.ingestion.base import BaseIngestor
from app.ingestion.chunking import RawDoc, build_chunks
from app.ingestion.policy import LegalSafeCrawlerPolicy
from app.schemas import DocumentChunk, SourceType
from app.utils.dates import parse_date

logger = logging.getLogger(__name__)


class KAPIngestor(BaseIngestor):
    def __init__(self, rate_limit_seconds: float = 1.0, max_retries: int = 3) -> None:
        self.rate_limit_seconds = rate_limit_seconds
        self.max_retries = max_retries
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "bist-agentic-rag/1.0"})
        self.policy = LegalSafeCrawlerPolicy()

    def _fetch(self, url: str) -> str:
        decision = self.policy.decide(url)
        if not decision.allowed:
            raise RuntimeError(f"Blocked by crawling policy: {decision.reason} ({url})")

        last_exc: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            try:
                self.policy.wait_rate_limit(url, custom_seconds=self.rate_limit_seconds)
                response = self.session.get(url, timeout=20)
                response.raise_for_status()
                return response.text
            except Exception as exc:  # noqa: BLE001
                logger.warning("KAP fetch failed (%s/%s) %s", attempt, self.max_retries, url)
                last_exc = exc
                time.sleep((self.rate_limit_seconds * attempt) + (0.5 * attempt))
        if last_exc:
            raise last_exc
        raise RuntimeError(f"Failed to fetch URL: {url}")

    @staticmethod
    def _extract_links(html: str, base_url: str) -> list[str]:
        soup = BeautifulSoup(html, "lxml")
        links: list[str] = []
        for a_tag in soup.select("a[href]"):
            href = a_tag["href"]
            if "Bildirim" in href or "/tr/Bildirim/" in href:
                links.append(urljoin(base_url, href))
        # de-duplicate while preserving order
        seen = set()
        deduped = []
        for link in links:
            if link not in seen:
                deduped.append(link)
                seen.add(link)
        return deduped[:50]

    @staticmethod
    def _parse_disclosure(html: str, url: str, ticker: str, institution: str) -> RawDoc:
        soup = BeautifulSoup(html, "lxml")
        title = (soup.title.string if soup.title else "KAP Disclosure").strip()
        body_candidates = soup.select("main, article, .content, .disclosure-content, body")
        body_text = ""
        for node in body_candidates:
            text = " ".join(node.get_text(separator=" ", strip=True).split())
            if len(text) > len(body_text):
                body_text = text

        date_str = None
        time_node = soup.select_one("time")
        if time_node and (time_node.get("datetime") or time_node.text):
            date_str = time_node.get("datetime") or time_node.text

        return RawDoc(
            ticker=ticker,
            source_type=SourceType.KAP,
            institution=institution,
            url=url,
            title=title,
            text=body_text or title,
            date=parse_date(date_str),
            published_at=parse_date(date_str),
            retrieved_at=datetime.utcnow().isoformat(),
            language="tr",
            confidence=0.95,
        )

    def collect(
        self,
        ticker: str,
        institution: str,
        source_urls: list[str],
        date_from: datetime | None = None,
        date_to: datetime | None = None,
    ) -> list[DocumentChunk]:
        collected: list[DocumentChunk] = []
        for src in source_urls:
            try:
                html = self._fetch(src)
            except Exception as exc:  # noqa: BLE001
                logger.warning("KAP source skipped for %s: %s", src, exc)
                continue
            links = self._extract_links(html, src)
            targets = links if links else [src]
            for url in targets:
                try:
                    disclosure_html = self._fetch(url) if url != src else html
                    raw = self._parse_disclosure(disclosure_html, url, ticker, institution)
                    if date_from and raw.date < date_from:
                        continue
                    if date_to and raw.date > date_to:
                        continue
                    collected.extend(build_chunks(raw))
                except Exception as exc:  # noqa: BLE001
                    logger.warning("KAP parse failed for %s: %s", url, exc)
        return collected
