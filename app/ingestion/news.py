from __future__ import annotations

import logging
import time
from datetime import datetime
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning
import warnings

from app.config import get_settings
from app.ingestion.base import BaseIngestor
from app.ingestion.chunking import RawDoc, build_chunks
from app.ingestion.policy import LegalSafeCrawlerPolicy
from app.market.entity_aliases import alias_keywords, entity_match_details
from app.schemas import DocumentChunk, SourceType
from app.utils.dates import now_utc, parse_date
from app.utils.text import normalize_visible_text, repair_mojibake

logger = logging.getLogger(__name__)
warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

PRIMARY_NEWS_FEEDS = [
    "https://www.aa.com.tr/tr/rss/default?cat=ekonomi",
    "https://www.paraanaliz.com/feed/",
    "https://www.bloomberght.com/rss",
    "https://www.ekonomim.com/rss",
    "https://bigpara.hurriyet.com.tr/rss/",
    "https://www.dunya.com/rss?dunya",
    "https://www.dunya.com/rss?sirketler",
    "https://www.dunya.com/rss?finans",
    "https://www.mynet.com/finans/rss/",
    "https://www.haberturk.com/rss/ekonomi.xml",
    "https://www.sozcu.com.tr/feed/?cat=ekonomi",
    "https://www.foreks.com/rss/feed",
    "https://tr.investing.com/rss/news_25.rss",
    "https://tr.investing.com/rss/news_285.rss",
]

DISCOVERY_NEWS_FEEDS = [
    "https://news.google.com/rss/search?q={ticker}%20BIST&hl=tr&gl=TR&ceid=TR:tr",
    "https://news.google.com/rss/search?q={ticker}%20hisse%20borsa&hl=tr&gl=TR&ceid=TR:tr",
    "https://news.google.com/rss/search?q={ticker}%20BIST%20KAP&hl=tr&gl=TR&ceid=TR:tr",
    "https://news.google.com/rss/search?q={ticker}%20bilanco%20finansal&hl=tr&gl=TR&ceid=TR:tr",
]

try:
    import feedparser
except Exception:  # noqa: BLE001
    feedparser = None


class NewsIngestor(BaseIngestor):
    def __init__(self, rate_limit_seconds: float = 4.0, max_retries: int = 3) -> None:
        self.settings = get_settings()
        self.rate_limit_seconds = rate_limit_seconds
        self.max_retries = max_retries
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "BIST-Agentic-RAG/2.2 (Academic Research Use)"})
        self.policy = LegalSafeCrawlerPolicy()
        self.last_policy_summary: dict[str, int | bool] = {
            "policy_applied": True,
            "blocked_count": 0,
            "retry_count": 0,
            "fetched_count": 0,
            "success_count": 0,
            "accepted_count": 0,
            "rejected_entity": 0,
            "last_success_at": "",
            "blocked_reason_counts": {},
            "source_counts": {},
            "rejected_samples": [],
        }

    @staticmethod
    def _institution_from_url(url: str, fallback: str) -> str:
        host = urlparse(url).netloc.lower()
        mapping = {
            "aa.com.tr": "AA",
            "www.aa.com.tr": "AA",
            "www.paraanaliz.com": "ParaAnaliz",
            "paraanaliz.com": "ParaAnaliz",
            "bloomberght.com": "Bloomberg HT",
            "www.bloomberght.com": "Bloomberg HT",
            "ekonomim.com": "Ekonomim",
            "www.ekonomim.com": "Ekonomim",
            "bigpara.hurriyet.com.tr": "Bigpara",
            "news.google.com": "Google News Discovery",
            "www.dunya.com": "Dünya Gazetesi",
            "dunya.com": "Dünya Gazetesi",
            "www.mynet.com": "Mynet Finans",
            "mynet.com": "Mynet Finans",
            "www.haberturk.com": "Habertürk",
            "haberturk.com": "Habertürk",
            "www.sozcu.com.tr": "Sözcü",
            "sozcu.com.tr": "Sözcü",
            "www.foreks.com": "Foreks",
            "foreks.com": "Foreks",
            "tr.investing.com": "Investing.com TR",
        }
        return mapping.get(host, fallback or host or "News")

    @staticmethod
    def _source_channel(url: str) -> str:
        host = urlparse(url).netloc.lower()
        if "news.google.com" in host:
            return "discovery"
        return "media"

    @classmethod
    def _source_reliability(cls, url: str) -> float:
        host = urlparse(url).netloc.lower()
        if "news.google.com" in host:
            return 0.55
        if "aa.com.tr" in host or "bloomberght.com" in host:
            return 0.72
        if "ekonomim.com" in host:
            return 0.70
        if "dunya.com" in host:
            return 0.74  # business newspaper of record
        if "foreks.com" in host:
            return 0.71
        if "investing.com" in host:
            return 0.68
        if "haberturk.com" in host or "sozcu.com.tr" in host:
            return 0.66
        if "bigpara.hurriyet.com.tr" in host:
            return 0.67
        if "paraanaliz.com" in host:
            return 0.66
        if "mynet.com" in host:
            return 0.63
        return 0.70

    def _default_feed_urls(self, ticker: str) -> list[str]:
        urls = list(PRIMARY_NEWS_FEEDS)
        if self.settings.news_enable_discovery:
            urls.extend(DISCOVERY_NEWS_FEEDS)
        return [url.format(ticker=ticker.upper()) if "{ticker}" in url else url for url in urls]

    def _fetch(self, url: str) -> str:
        decision = self.policy.decide(url)
        if not decision.allowed:
            self.last_policy_summary["blocked_count"] = int(self.last_policy_summary["blocked_count"]) + 1
            reasons = dict(self.last_policy_summary.get("blocked_reason_counts", {}))
            reasons[decision.reason] = int(reasons.get(decision.reason, 0)) + 1
            self.last_policy_summary["blocked_reason_counts"] = reasons
            raise RuntimeError(f"Blocked by crawling policy: {decision.reason} ({url})")

        last_exc: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            try:
                self.policy.wait_rate_limit(url, custom_seconds=self.rate_limit_seconds)
                response = self.session.get(url, timeout=20)
                response.raise_for_status()
                response.encoding = response.apparent_encoding or response.encoding or "utf-8"
                self.last_policy_summary["fetched_count"] = int(self.last_policy_summary["fetched_count"]) + 1
                return repair_mojibake(response.text)
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                logger.warning("News fetch failed (%s/%s) %s", attempt, self.max_retries, url)
                self.last_policy_summary["retry_count"] = int(self.last_policy_summary["retry_count"]) + 1
                time.sleep((self.rate_limit_seconds * attempt) + (0.5 * attempt))
        if last_exc:
            raise last_exc
        raise RuntimeError(f"Failed to fetch URL: {url}")

    @classmethod
    def _parse_article(cls, html: str, url: str, ticker: str, institution: str) -> RawDoc:
        soup = BeautifulSoup(html, "lxml")
        title = normalize_visible_text(soup.title.string if soup.title else "News")
        body_candidates = soup.select("article, main, .article, .news-content, body")
        text = ""
        for node in body_candidates:
            candidate = normalize_visible_text(node.get_text(separator=" ", strip=True))
            if len(candidate) > len(text):
                text = candidate
        date_tag = soup.select_one("time")
        date_str = date_tag.get("datetime") if date_tag and date_tag.get("datetime") else None
        authors = " ".join(node.get_text(" ", strip=True) for node in soup.select('[rel="author"], .author, .article-author')[:2])
        return RawDoc(
            ticker=ticker,
            source_type=SourceType.NEWS,
            institution=cls._institution_from_url(url, institution),
            url=url,
            title=title,
            text=text or title,
            date=parse_date(date_str),
            published_at=parse_date(date_str),
            retrieved_at=now_utc().isoformat(),
            notification_type="General Assembly",
            language="tr",
            confidence=0.76,
            metadata={
                "source_channel": cls._source_channel(url),
                "source_reliability": cls._source_reliability(url),
                "author": normalize_visible_text(authors),
                "entity_aliases": sorted(alias_keywords(ticker)),
                "discovered_via": "article_fetch",
            },
        )

    def _entity_match(self, text: str, ticker: str, *, title: str = "", source_label: str = "") -> dict[str, object]:
        details = entity_match_details(text, ticker, title=title, source_label=source_label)
        if float(details.get("score", 0.0)) < 0.34:
            self.last_policy_summary["rejected_entity"] = int(self.last_policy_summary.get("rejected_entity", 0)) + 1
            rejected = list(self.last_policy_summary.get("rejected_samples", []))
            if len(rejected) < 16:
                rejected.append(
                    {
                        "title": normalize_visible_text(title)[:140] or "Untitled",
                        "source": source_label or "News",
                        "score": float(details.get("score", 0.0)),
                        "reason": str(details.get("reason", "rejected")),
                    }
                )
            self.last_policy_summary["rejected_samples"] = rejected
        return details

    def _record_source_accept(self, source_label: str) -> None:
        self.last_policy_summary["accepted_count"] = int(self.last_policy_summary.get("accepted_count", 0)) + 1
        counts = dict(self.last_policy_summary.get("source_counts", {}))
        counts[source_label] = int(counts.get(source_label, 0)) + 1
        self.last_policy_summary["source_counts"] = counts

    @staticmethod
    def _summary_text(raw_summary: str) -> str:
        summary = raw_summary or ""
        parser = "xml" if "<rss" in summary or "<feed" in summary or "<entry" in summary else "lxml"
        return BeautifulSoup(summary, parser).get_text(" ", strip=True)

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
        try:
            raw_feed = self._fetch(rss_url)
        except Exception as exc:  # noqa: BLE001
            logger.warning("RSS fetch failed for %s: %s", rss_url, exc)
            return []
        feed = feedparser.parse(raw_feed)
        chunks: list[DocumentChunk] = []
        feed_institution = self._institution_from_url(rss_url, institution)
        for entry in feed.entries:
            published = parse_date(entry.get("published") or entry.get("updated"))
            if date_from and published < date_from:
                continue
            if date_to and published > date_to:
                continue
            title = normalize_visible_text(entry.get("title", "News"))
            summary = self._summary_text(entry.get("summary", ""))
            link = entry.get("link", rss_url)
            source_label = self._institution_from_url(link or rss_url, feed_institution)
            entry_text = f"{title} {summary} {link}"
            match = self._entity_match(entry_text, ticker, title=title, source_label=source_label)
            if float(match.get("score", 0.0)) < 0.34:
                continue
            metadata = {
                "source_channel": self._source_channel(link or rss_url),
                "source_reliability": self._source_reliability(link or rss_url),
                "author": normalize_visible_text(entry.get("author", "")),
                "entity_aliases": sorted(alias_keywords(ticker)),
                "discovered_via": rss_url,
                "entity_score": float(match.get("score", 0.0)),
                "entity_reason": match.get("reason", ""),
            }

            raw: RawDoc
            if link and link != rss_url and len(summary) < 160:
                try:
                    html = self._fetch(link)
                    article_raw = self._parse_article(html, link, ticker, source_label)
                    article_match = self._entity_match(
                        f"{article_raw.title} {article_raw.text} {article_raw.url}",
                        ticker,
                        title=article_raw.title,
                        source_label=source_label,
                    )
                    if float(article_match.get("score", 0.0)) >= 0.34:
                        raw = article_raw
                        if published:
                            raw.date = published
                            raw.published_at = published
                        raw.confidence = max(raw.confidence, min(0.92, float(article_match.get("score", 0.0))))
                        raw.metadata["entity_score"] = float(article_match.get("score", 0.0))
                        raw.metadata["entity_reason"] = article_match.get("reason", "")
                    else:
                        raise RuntimeError("rss_article_ticker_mismatch")
                except Exception:
                    raw = RawDoc(
                        ticker=ticker,
                        source_type=SourceType.NEWS,
                        institution=source_label,
                        url=link,
                        title=title,
                        text=normalize_visible_text(summary or entry.get("title", "")),
                        date=published,
                        published_at=published,
                        retrieved_at=now_utc().isoformat(),
                        notification_type="General Assembly",
                        language="tr",
                        confidence=max(0.68, min(0.88, float(match.get("score", 0.0)))),
                        metadata=metadata,
                    )
            else:
                raw = RawDoc(
                    ticker=ticker,
                    source_type=SourceType.NEWS,
                    institution=source_label,
                    url=link,
                    title=title,
                    text=normalize_visible_text(summary or entry.get("title", "")),
                    date=published,
                    published_at=published,
                    retrieved_at=now_utc().isoformat(),
                    notification_type="General Assembly",
                    language="tr",
                    confidence=max(0.68, min(0.88, float(match.get("score", 0.0)))),
                    metadata=metadata,
                )
            chunks.extend(build_chunks(raw))
            self._record_source_accept(source_label)
        if chunks:
            self.last_policy_summary["success_count"] = int(self.last_policy_summary["success_count"]) + 1
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
        resolved_urls = (
            [url.format(ticker=ticker.upper()) if "{ticker}" in url else url for url in source_urls]
            if source_urls
            else self._default_feed_urls(ticker)
        )
        self.last_policy_summary = {
            "policy_applied": True,
            "blocked_count": 0,
            "retry_count": 0,
            "fetched_count": 0,
            "success_count": 0,
            "accepted_count": 0,
            "rejected_entity": 0,
            "last_success_at": "",
            "blocked_reason_counts": {},
            "source_counts": {},
            "rejected_samples": [],
        }
        all_chunks: list[DocumentChunk] = []
        failed_count = 0
        for src in resolved_urls:
            src_lower = src.lower()
            if "rss" in src_lower or src_lower.endswith(".xml"):
                all_chunks.extend(self._collect_from_rss(src, ticker, institution, date_from, date_to))
                continue

            try:
                html = self._fetch(src)
                raw = self._parse_article(html, src, ticker, institution)
                source_label = self._institution_from_url(src, institution)
                match = self._entity_match(
                    f"{raw.title} {raw.text} {raw.url}",
                    ticker,
                    title=raw.title,
                    source_label=source_label,
                )
                if float(match.get("score", 0.0)) < 0.34:
                    continue
                if date_from and raw.date < date_from:
                    continue
                if date_to and raw.date > date_to:
                    continue
                raw.confidence = max(raw.confidence, min(0.92, float(match.get("score", 0.0))))
                raw.metadata["entity_score"] = float(match.get("score", 0.0))
                raw.metadata["entity_reason"] = match.get("reason", "")
                all_chunks.extend(build_chunks(raw))
                self._record_source_accept(source_label)
                self.last_policy_summary["success_count"] = int(self.last_policy_summary["success_count"]) + 1
            except Exception as exc:  # noqa: BLE001
                logger.warning("News parse failed for %s: %s", src, exc)
                failed_count += 1

        if failed_count > 0 and not all_chunks and self.settings.news_enable_discovery:
            logger.warning("Primary news sources failed. Trying discovery feeds.")
            for feed_url in DISCOVERY_NEWS_FEEDS:
                resolved = feed_url.format(ticker=ticker.upper()) if "{ticker}" in feed_url else feed_url
                all_chunks.extend(self._collect_from_rss(resolved, ticker, institution, date_from, date_to))
        if all_chunks:
            self.last_policy_summary["last_success_at"] = now_utc().isoformat()
        return all_chunks
