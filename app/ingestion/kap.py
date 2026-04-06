from __future__ import annotations

import logging
import time
from datetime import datetime
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from app.config import get_settings
from app.ingestion.base import BaseIngestor
from app.ingestion.chunking import RawDoc, build_chunks
from app.ingestion.policy import LegalSafeCrawlerPolicy
from app.ingestion.validation import normalize_notification_type
from app.schemas import DocumentChunk, SourceType
from app.utils.dates import now_utc, parse_date

logger = logging.getLogger(__name__)


class KAPIngestor(BaseIngestor):
    def __init__(self, rate_limit_seconds: float = 4.0, max_retries: int = 3) -> None:
        self.settings = get_settings()
        self.rate_limit_seconds = rate_limit_seconds
        self.max_retries = max_retries
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "BIST-Agentic-RAG/2.0 (Academic Research Use)"})
        self.policy = LegalSafeCrawlerPolicy()
        self.last_policy_summary: dict[str, int | bool] = {
            "policy_applied": True,
            "blocked_count": 0,
            "retry_count": 0,
        }

    def _fetch(self, url: str) -> str:
        decision = self.policy.decide(url)
        if not decision.allowed:
            self.last_policy_summary["blocked_count"] = int(self.last_policy_summary["blocked_count"]) + 1
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
                self.last_policy_summary["retry_count"] = int(self.last_policy_summary["retry_count"]) + 1
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
    def _infer_notification_type(title: str, body_text: str) -> str:
        haystack = f"{title} {body_text}".lower()
        if "özel durum" in haystack or "material event" in haystack:
            return "Material Event"
        if "finansal" in haystack or "financial report" in haystack:
            return "Financial Report"
        if "yönetim kurulu" in haystack or "board decision" in haystack:
            return "Board Decision"
        if "genel kurul" in haystack or "general assembly" in haystack:
            return "General Assembly"
        return "Material Event"

    def _collect_from_api(
        self,
        ticker: str,
        institution: str,
        date_from: datetime | None,
        date_to: datetime | None,
        notification_types: list[str] | None,
    ) -> list[DocumentChunk]:
        template = self.settings.kap_api_disclosure_url_template.strip()
        api_key = self.settings.kap_api_key.strip()
        if not template or not api_key:
            return []

        url = template.format(ticker=ticker.upper())
        response = self.session.get(url, headers={"Authorization": f"Bearer {api_key}"}, timeout=20)
        response.raise_for_status()
        payload = response.json()
        rows = payload if isinstance(payload, list) else payload.get("items", [])
        wanted_types = {normalize_notification_type(item) for item in (notification_types or [])}
        chunks: list[DocumentChunk] = []
        for row in rows:
            publication = parse_date(
                row.get("publication_date")
                or row.get("date")
                or row.get("published_at")
                or row.get("publishedAt")
            )
            ntype = normalize_notification_type(
                row.get("notification_type") or row.get("notificationType") or "Material Event"
            )
            if wanted_types and ntype not in wanted_types:
                continue
            if date_from and publication < date_from:
                continue
            if date_to and publication > date_to:
                continue

            raw = RawDoc(
                ticker=ticker,
                source_type=SourceType.KAP,
                institution=row.get("institution") or institution or "KAP",
                url=row.get("url") or "",
                title=row.get("title") or "KAP Disclosure",
                text=row.get("text") or row.get("content") or "",
                date=publication,
                published_at=publication,
                retrieved_at=now_utc().isoformat(),
                notification_type=ntype,
                language=row.get("language") or "tr",
                confidence=float(row.get("confidence", 0.96)),
            )
            chunks.extend(build_chunks(raw))
        return chunks

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

        notification_type = normalize_notification_type(KAPIngestor._infer_notification_type(title, body_text))
        return RawDoc(
            ticker=ticker,
            source_type=SourceType.KAP,
            institution=institution,
            url=url,
            title=title,
            text=body_text or title,
            date=parse_date(date_str),
            published_at=parse_date(date_str),
            retrieved_at=now_utc().isoformat(),
            notification_type=notification_type,
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
        notification_types: list[str] | None = None,
    ) -> list[DocumentChunk]:
        if self.settings.kap_api_key and self.settings.kap_api_disclosure_url_template:
            try:
                api_chunks = self._collect_from_api(ticker, institution, date_from, date_to, notification_types)
                if api_chunks:
                    return api_chunks
            except Exception as exc:  # noqa: BLE001
                logger.warning("KAP API mode failed; switching to crawler fallback: %s", exc)

        self.last_policy_summary = {"policy_applied": True, "blocked_count": 0, "retry_count": 0}
        collected: list[DocumentChunk] = []
        wanted_types = {normalize_notification_type(item) for item in (notification_types or [])}
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
                    if wanted_types and raw.notification_type not in wanted_types:
                        continue
                    if date_from and raw.date < date_from:
                        continue
                    if date_to and raw.date > date_to:
                        continue
                    collected.extend(build_chunks(raw))
                except Exception as exc:  # noqa: BLE001
                    logger.warning("KAP parse failed for %s: %s", url, exc)
        return collected
