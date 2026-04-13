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
from app.ingestion.kap_api import KAPAPIClient
from app.ingestion.policy import LegalSafeCrawlerPolicy
from app.ingestion.validation import normalize_notification_type
from app.schemas import DocumentChunk, SourceType
from app.utils.dates import now_utc, parse_date
from app.utils.text import normalize_visible_text, repair_mojibake

logger = logging.getLogger(__name__)


class KAPIngestor(BaseIngestor):
    def __init__(self, rate_limit_seconds: float = 4.0, max_retries: int = 3) -> None:
        self.settings = get_settings()
        self.rate_limit_seconds = rate_limit_seconds
        self.max_retries = max_retries
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "BIST-Agentic-RAG/2.0 (Academic Research Use)"})
        self.policy = LegalSafeCrawlerPolicy()
        # Public KAP REST client is the primary path; HTML scraper below is
        # the fallback when the JSON API is blocked or empty.
        self.api_client = KAPAPIClient(rate_limit_seconds=max(2.0, rate_limit_seconds * 0.6))
        self.last_policy_summary: dict[str, int | bool | str | dict[str, int]] = {
            "policy_applied": True,
            "blocked_count": 0,
            "retry_count": 0,
            "fetched_count": 0,
            "success_count": 0,
            "last_success_at": "",
            "blocked_reason_counts": {},
            "mode": "html_scraper",
        }

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
                self.last_policy_summary["fetched_count"] = int(self.last_policy_summary["fetched_count"]) + 1
                return self._decode_response_text(response)
            except Exception as exc:  # noqa: BLE001
                logger.warning("KAP fetch failed (%s/%s) %s", attempt, self.max_retries, url)
                last_exc = exc
                self.last_policy_summary["retry_count"] = int(self.last_policy_summary["retry_count"]) + 1
                time.sleep((self.rate_limit_seconds * attempt) + (0.5 * attempt))
        if last_exc:
            raise last_exc
        raise RuntimeError(f"Failed to fetch URL: {url}")

    @staticmethod
    def _decode_response_text(response: requests.Response) -> str:
        candidates = ["utf-8", response.encoding, response.apparent_encoding, "windows-1254", "latin1"]
        seen: set[str] = set()
        for encoding in [item for item in candidates if item]:
            normalized_encoding = str(encoding).strip().lower()
            if not normalized_encoding or normalized_encoding in seen:
                continue
            seen.add(normalized_encoding)
            try:
                decoded = response.content.decode(normalized_encoding, errors="strict")
            except Exception:  # noqa: BLE001
                continue
            repaired = repair_mojibake(decoded)
            if not any(marker in repaired for marker in ("?", "?", "?")):
                return repaired
        return repair_mojibake(response.text)

    @staticmethod
    def _extract_links(html: str, base_url: str) -> list[str]:
        soup = BeautifulSoup(html, "lxml")
        links: list[str] = []
        for a_tag in soup.select("a[href]"):
            href = a_tag["href"]
            href_lower = href.lower()
            if (
                "bildirim" in href_lower
                or "/tr/bildirim/" in href_lower
                or "/tr/bildirimleri/" in href_lower
                or "bildirim-sorgu-sonuc" in href_lower
            ):
                links.append(urljoin(base_url, href))
        seen = set()
        deduped = []
        for link in links:
            if link not in seen:
                deduped.append(link)
                seen.add(link)
        return deduped[:50]

    @staticmethod
    def _infer_notification_type(title: str, body_text: str) -> str:
        haystack = normalize_visible_text(f"{title} {body_text}").lower()
        if "?zel durum" in haystack or "ozel durum" in haystack or "material event" in haystack:
            return "Material Event"
        if "finansal" in haystack or "financial report" in haystack:
            return "Financial Report"
        if "y?netim kurulu" in haystack or "yonetim kurulu" in haystack or "board decision" in haystack:
            return "Board Decision"
        if "genel kurul" in haystack or "general assembly" in haystack:
            return "General Assembly"
        return "Material Event"

    @staticmethod
    def _has_disclosure_markers(text: str) -> bool:
        haystack = normalize_visible_text(text).lower()
        markers = [
            "g?nderim tarihi",
            "gonderim tarihi",
            "bildirim tipi",
            "?zet bilgi",
            "ozet bilgi",
            "yap?lan a??klama",
            "yapilan aciklama",
            "?zel durum a??klamas?",
            "ozel durum aciklamasi",
            "genel kurul i?lemlerine ili?kin bildirim",
            "genel kurul islemlerine iliskin bildirim",
            "financial report",
            "board decision",
            "?irketin ?n?m?zdeki bir ayl?k hak kullan?mlar?",
            "sirketin onumuzdeki bir aylik hak kullanimlari",
            "?irketten beklenen ilk be? periyodik bildirim",
            "sirketten beklenen ilk bes periyodik bildirim",
            "y?l baz?nda ?irket haberleri",
            "yil bazinda sirket haberleri",
        ]
        return any(marker in haystack for marker in markers)

    @staticmethod
    def _is_navigation_heavy(text: str) -> bool:
        haystack = normalize_visible_text(text).lower()
        navigation_markers = [
            "bildirim sorgular?",
            "bildirim sorgulari",
            "bug?n gelen bildirimler",
            "bugun gelen bildirimler",
            "beklenen bildirimler",
            "detayl? sorgulama",
            "detayli sorgulama",
            "yat?r?m kurulu?lar?",
            "yatirim kuruluslari",
            "portf?y y?netim ?irketleri",
            "portfoy yonetim sirketleri",
        ]
        return sum(1 for marker in navigation_markers if marker in haystack) >= 3

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
                institution=normalize_visible_text(row.get("institution") or institution or "KAP"),
                url=row.get("url") or "",
                title=normalize_visible_text(row.get("title") or "KAP Disclosure"),
                text=normalize_visible_text(row.get("text") or row.get("content") or ""),
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
        title = normalize_visible_text(soup.title.string if soup.title else "KAP Disclosure")
        body_candidates = soup.select(
            "article, main, .content, .disclosure-content, .detail-content, .type-general, .modal-body, body"
        )
        body_text = ""
        for node in body_candidates:
            text = normalize_visible_text(node.get_text(separator=" ", strip=True))
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
            institution=normalize_visible_text(institution),
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
        # Path 1 — legacy bearer-token KAP API (only if a private template is wired in)
        if self.settings.kap_api_key and self.settings.kap_api_disclosure_url_template:
            try:
                api_chunks = self._collect_from_api(ticker, institution, date_from, date_to, notification_types)
                if api_chunks:
                    return api_chunks
            except Exception as exc:  # noqa: BLE001
                logger.warning("KAP private API mode failed; trying public REST: %s", exc)

        # Path 2 — public KAP REST API (preferred). No keys required.
        try:
            public_chunks = self.api_client.collect_disclosures(
                ticker,
                date_from=date_from,
                date_to=date_to,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("KAP public REST collection failed for %s: %s", ticker, exc)
            public_chunks = []

        wanted_types_local = {normalize_notification_type(item) for item in (notification_types or [])}
        if wanted_types_local:
            public_chunks = [c for c in public_chunks if c.notification_type in wanted_types_local]

        if public_chunks:
            self.last_policy_summary = {
                "policy_applied": True,
                "blocked_count": int(self.api_client.last_telemetry.get("blocked_count", 0)),
                "retry_count": int(self.api_client.last_telemetry.get("retry_count", 0)),
                "fetched_count": int(self.api_client.last_telemetry.get("fetched_count", 0)),
                "success_count": int(self.api_client.last_telemetry.get("success_count", 0)),
                "last_success_at": self.api_client.last_telemetry.get("last_success_at", ""),
                "blocked_reason_counts": dict(
                    self.api_client.last_telemetry.get("blocked_reason_counts", {})
                ),
                "mode": "rest_api",
                "endpoint_counts": dict(
                    self.api_client.last_telemetry.get("endpoint_counts", {})
                ),
            }
            return public_chunks

        # Path 3 — HTML scraper fallback
        self.last_policy_summary = {
            "policy_applied": True,
            "blocked_count": 0,
            "retry_count": 0,
            "fetched_count": 0,
            "success_count": 0,
            "last_success_at": "",
            "blocked_reason_counts": {},
            "mode": "html_scraper",
        }
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
                    raw_text = f"{raw.title} {raw.text}"
                    if self._is_navigation_heavy(raw_text):
                        continue
                    if "/bildirim/" not in url.lower() and "/bildirimleri/" not in url.lower() and not self._has_disclosure_markers(raw_text):
                        continue
                    if wanted_types and raw.notification_type not in wanted_types:
                        continue
                    if date_from and raw.date < date_from:
                        continue
                    if date_to and raw.date > date_to:
                        continue
                    built = build_chunks(raw)
                    collected.extend(built)
                    if built:
                        self.last_policy_summary["success_count"] = int(self.last_policy_summary["success_count"]) + 1
                except Exception as exc:  # noqa: BLE001
                    logger.warning("KAP parse failed for %s: %s", url, exc)
        if collected:
            self.last_policy_summary["last_success_at"] = now_utc().isoformat()
        return collected

    def collect_quick(
        self,
        ticker: str,
        institution: str,
        source_urls: list[str],
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        notification_types: list[str] | None = None,
    ) -> list[DocumentChunk]:
        _ = date_from, date_to, notification_types
        self.last_policy_summary = {
            "policy_applied": True,
            "blocked_count": 0,
            "retry_count": 0,
            "fetched_count": 0,
            "success_count": 0,
            "last_success_at": "",
            "blocked_reason_counts": {},
        }
        collected: list[DocumentChunk] = []
        for src in source_urls[:2]:
            try:
                html = self._fetch(src)
                raw = self._parse_disclosure(html, src, ticker, institution)
                raw.notification_type = normalize_notification_type(raw.notification_type or "Official Profile")
                raw.confidence = min(float(raw.confidence or 0.8), 0.8)
                raw.text = raw.text[:5000]
                if self._is_navigation_heavy(f"{raw.title} {raw.text}"):
                    continue
                built = build_chunks(raw)
                collected.extend(built)
                if built:
                    self.last_policy_summary["success_count"] = int(self.last_policy_summary["success_count"]) + 1
            except Exception as exc:  # noqa: BLE001
                logger.warning("KAP quick probe failed for %s: %s", src, exc)
        if collected:
            self.last_policy_summary["last_success_at"] = now_utc().isoformat()
        return collected
