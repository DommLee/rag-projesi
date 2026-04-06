from __future__ import annotations

import logging
import time
from datetime import datetime

import requests
from bs4 import BeautifulSoup

from app.ingestion.base import BaseIngestor
from app.ingestion.chunking import RawDoc, build_chunks
from app.ingestion.policy import LegalSafeCrawlerPolicy
from app.schemas import DocumentChunk, SourceType
from app.utils.dates import now_utc, parse_date

logger = logging.getLogger(__name__)
FAILOVER_NEWS_FEEDS = [
    "https://www.aa.com.tr/tr/rss/default?cat=ekonomi",
    "https://www.aa.com.tr/tr/rss/default?cat=finans",
]

try:
    import feedparser
except Exception:  # noqa: BLE001
    feedparser = None


class NewsIngestor(BaseIngestor):
    def __init__(self, rate_limit_seconds: float = 4.0, max_retries: int = 3) -> None:
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
                last_exc = exc
                logger.warning("News fetch failed (%s/%s) %s", attempt, self.max_retries, url)
                self.last_policy_summary["retry_count"] = int(self.last_policy_summary["retry_count"]) + 1
                time.sleep((self.rate_limit_seconds * attempt) + (0.5 * attempt))
        if last_exc:
            raise last_exc
        raise RuntimeError(f"Failed to fetch URL: {url}")

    @staticmethod
    def _parse_article(html: str, url: str, ticker: str, institution: str) -> RawDoc:
        soup = BeautifulSoup(html, "lxml")
        title = (soup.title.string if soup.title else "News").strip()
        body_candidates = soup.select("article, main, .article, .news-content, body")
        text = ""
        for node in body_candidates:
            candidate = " ".join(node.get_text(separator=" ", strip=True).split())
            if len(candidate) > len(text):
                text = candidate
        date_tag = soup.select_one("time")
        date_str = date_tag.get("datetime") if date_tag and date_tag.get("datetime") else None
        return RawDoc(
            ticker=ticker,
            source_type=SourceType.NEWS,
            institution=institution,
            url=url,
            title=title,
            text=text or title,
            date=parse_date(date_str),
            published_at=parse_date(date_str),
            retrieved_at=now_utc().isoformat(),
            notification_type="General Assembly",
            language="tr",
            confidence=0.75,
        )

    def _collect_from_rss(
        self,
        rss_url: str,
        ticker: str,
        institution: str,
        date_from: datetime | None,
        date_to: datetime | None,
    ) -> list[DocumentChunk]:
        if feedparser is None:
            logger.warning("feedparser not installed. RSS URL skipped: %s", rss_url)
            return []
        feed = feedparser.parse(rss_url)
        chunks: list[DocumentChunk] = []
        for entry in feed.entries:
            published = parse_date(entry.get("published") or entry.get("updated"))
            if date_from and published < date_from:
                continue
            if date_to and published > date_to:
                continue
            summary = BeautifulSoup(entry.get("summary", ""), "lxml").get_text(" ", strip=True)
            raw = RawDoc(
                ticker=ticker,
                source_type=SourceType.NEWS,
                institution=institution,
                url=entry.get("link", rss_url),
                title=entry.get("title", "News"),
                text=summary or entry.get("title", ""),
                date=published,
                published_at=published,
                retrieved_at=now_utc().isoformat(),
                notification_type="General Assembly",
                language="tr",
                confidence=0.7,
            )
            chunks.extend(build_chunks(raw))
        return chunks

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
        self.last_policy_summary = {"policy_applied": True, "blocked_count": 0, "retry_count": 0}
        all_chunks: list[DocumentChunk] = []
        failed_count = 0
        for src in source_urls:
            src_lower = src.lower()
            if "rss" in src_lower or src_lower.endswith(".xml"):
                all_chunks.extend(self._collect_from_rss(src, ticker, institution, date_from, date_to))
                continue

            try:
                html = self._fetch(src)
                raw = self._parse_article(html, src, ticker, institution)
                if date_from and raw.date < date_from:
                    continue
                if date_to and raw.date > date_to:
                    continue
                all_chunks.extend(build_chunks(raw))
            except Exception as exc:  # noqa: BLE001
                logger.warning("News parse failed for %s: %s", src, exc)
                failed_count += 1

        if failed_count > 0 and not all_chunks:
            logger.warning("Primary news sources failed. Trying failover feeds.")
            for feed_url in FAILOVER_NEWS_FEEDS:
                all_chunks.extend(self._collect_from_rss(feed_url, ticker, institution, date_from, date_to))
        return all_chunks
