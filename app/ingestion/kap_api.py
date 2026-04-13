"""Public KAP REST API client.

KAP (Kamuyu Aydınlatma Platformu) exposes a public REST surface used by its
own Next.js frontend. We hit the same endpoints rather than scraping HTML so
that disclosures arrive as structured JSON with stable field names.

Endpoints used (verified against the public website):

* ``POST /tr/api/search/combined``
    Resolve a ticker (e.g. ``ASELS``) to KAP's internal ``memberOrFundOid``.
* ``POST /tr/api/disclosure/members/byCriteria``
    Historical disclosure list filtered by date range, disclosure class
    (FR / ODA / DG) and subject id.
* ``POST /tr/api/expected-disclosure-inquiry/company``
    Forward-looking expected disclosure calendar for a company.
* ``GET  /tr/api/company-detail/disclosures/{type}/{company_id}``
    Per-type disclosure list (FAR, KYUR, SUR, KDP, DEG, UNV, SYI).
* ``GET  /tr/Bildirim/{disclosureIndex}``
    HTML notification page used to extract the full body text and any
    attached PDF link, since the JSON list only carries title + summary.

The client is read-only, runs through ``LegalSafeCrawlerPolicy`` so robots.txt
and rate limits are respected, and falls back gracefully if KAP changes its
schema. The HTML scraper in ``app/ingestion/kap.py`` remains as a secondary
path; this module is the new primary source whenever the API answers.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

import requests
from bs4 import BeautifulSoup

from app.config import get_settings
from app.ingestion.chunking import RawDoc, build_chunks
from app.ingestion.policy import LegalSafeCrawlerPolicy
from app.ingestion.validation import normalize_notification_type
from app.schemas import DocumentChunk, SourceType
from app.utils.dates import now_utc, parse_date
from app.utils.text import normalize_visible_text, repair_mojibake

logger = logging.getLogger(__name__)


KAP_BASE = "https://www.kap.org.tr"
SEARCH_URL = f"{KAP_BASE}/tr/api/search/combined"
DISCLOSURE_BY_CRITERIA_URL = f"{KAP_BASE}/tr/api/disclosure/members/byCriteria"
EXPECTED_DISCLOSURE_URL = f"{KAP_BASE}/tr/api/expected-disclosure-inquiry/company"
DISCLOSURE_BY_TYPE_URL = f"{KAP_BASE}/tr/api/company-detail/disclosures/{{type}}/{{company_id}}"
NOTIFICATION_HTML_URL = f"{KAP_BASE}/tr/Bildirim/{{disclosure_index}}"


# Disclosure subject UUIDs are stable on KAP — these come from the public
# disclosure-subjects API. Adding more here is safe; the client never trims
# the list.
DISCLOSURE_SUBJECTS: dict[str, str] = {
    "financial_report": "4028328c594bfdca01594c0af9aa0057",
    "operating_review": "4028328d594c04f201594c5155dd0076",
}

# Maps KAP disclosure-type codes to canonical notification_type values used
# inside our metadata schema.
TYPE_TO_NOTIFICATION = {
    "FR": "Financial Report",
    "ODA": "Material Event",
    "DG": "Material Event",
    "FAR": "Financial Report",
    "KYUR": "Board Decision",
    "SUR": "Material Event",
    "KDP": "Board Decision",
    "DEG": "Material Event",
    "UNV": "Material Event",
    "SYI": "Material Event",
}


@dataclass
class KAPCompanyRef:
    ticker: str
    company_id: str
    name: str


class KAPAPIClient:
    """Thin, defensive wrapper over KAP's public JSON endpoints."""

    def __init__(
        self,
        *,
        rate_limit_seconds: float = 2.5,
        request_timeout: float = 20.0,
        max_retries: int = 2,
    ) -> None:
        self.settings = get_settings()
        self.rate_limit_seconds = rate_limit_seconds
        self.request_timeout = request_timeout
        self.max_retries = max_retries
        self.policy = LegalSafeCrawlerPolicy()
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": self.settings.crawler_user_agent,
                "Accept": "application/json, text/plain, */*",
                "Accept-Language": "tr-TR,tr;q=0.9,en;q=0.8",
                "Origin": KAP_BASE,
                "Referer": f"{KAP_BASE}/tr",
            }
        )
        self._company_cache: dict[str, KAPCompanyRef] = {}
        self.last_telemetry: dict[str, Any] = self._fresh_telemetry()

    # ------------------------------------------------------------------ #
    # Telemetry / health
    # ------------------------------------------------------------------ #
    @staticmethod
    def _fresh_telemetry() -> dict[str, Any]:
        return {
            "policy_applied": True,
            "api_calls": 0,
            "blocked_count": 0,
            "fetched_count": 0,
            "success_count": 0,
            "retry_count": 0,
            "last_success_at": "",
            "blocked_reason_counts": {},
            "endpoint_counts": {},
            "mode": "rest_api",
        }

    def _record_endpoint(self, label: str) -> None:
        counts = dict(self.last_telemetry.get("endpoint_counts", {}))
        counts[label] = int(counts.get(label, 0)) + 1
        self.last_telemetry["endpoint_counts"] = counts

    def _record_blocked(self, reason: str) -> None:
        self.last_telemetry["blocked_count"] = int(self.last_telemetry["blocked_count"]) + 1
        reasons = dict(self.last_telemetry.get("blocked_reason_counts", {}))
        reasons[reason] = int(reasons.get(reason, 0)) + 1
        self.last_telemetry["blocked_reason_counts"] = reasons

    # ------------------------------------------------------------------ #
    # Low level HTTP
    # ------------------------------------------------------------------ #
    def _request(
        self,
        method: str,
        url: str,
        *,
        json_body: dict[str, Any] | None = None,
        endpoint_label: str = "",
    ) -> requests.Response | None:
        decision = self.policy.decide(url)
        if not decision.allowed:
            self._record_blocked(decision.reason)
            logger.warning("KAP API call blocked by policy: %s -> %s", url, decision.reason)
            return None

        last_exc: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            try:
                self.policy.wait_rate_limit(url, custom_seconds=self.rate_limit_seconds)
                response = self.session.request(
                    method,
                    url,
                    json=json_body,
                    timeout=self.request_timeout,
                )
                self.last_telemetry["api_calls"] = int(self.last_telemetry["api_calls"]) + 1
                self.last_telemetry["fetched_count"] = int(self.last_telemetry["fetched_count"]) + 1
                if response.status_code >= 400:
                    raise RuntimeError(f"http_{response.status_code}")
                if endpoint_label:
                    self._record_endpoint(endpoint_label)
                return response
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                self.last_telemetry["retry_count"] = int(self.last_telemetry["retry_count"]) + 1
                logger.warning(
                    "KAP API request failed (%s/%s) %s -> %s",
                    attempt,
                    self.max_retries,
                    url,
                    exc,
                )
        if last_exc:
            logger.warning("KAP API gave up on %s after %s retries", url, self.max_retries)
        return None

    # ------------------------------------------------------------------ #
    # Company lookup
    # ------------------------------------------------------------------ #
    def lookup_company(self, ticker: str) -> KAPCompanyRef | None:
        ticker_norm = ticker.strip().upper()
        if not ticker_norm:
            return None
        if ticker_norm in self._company_cache:
            return self._company_cache[ticker_norm]

        response = self._request(
            "POST",
            SEARCH_URL,
            json_body={"keyword": ticker_norm},
            endpoint_label="search/combined",
        )
        if response is None:
            return None
        try:
            payload = response.json()
        except Exception:  # noqa: BLE001
            logger.warning("KAP search returned non-JSON for %s", ticker_norm)
            return None

        candidates: list[dict[str, Any]] = []
        if isinstance(payload, list):
            for category_obj in payload:
                if not isinstance(category_obj, dict):
                    continue
                if category_obj.get("category") not in {"companyOrFunds", "companies", "company"}:
                    continue
                results = category_obj.get("results") or []
                for item in results:
                    if not isinstance(item, dict):
                        continue
                    code = (item.get("cmpOrFundCode") or "").upper()
                    if not code:
                        continue
                    candidates.append(item)

        # Prefer exact ticker match.
        chosen: dict[str, Any] | None = None
        for cand in candidates:
            if (cand.get("cmpOrFundCode") or "").upper() == ticker_norm:
                chosen = cand
                break
        if chosen is None and candidates:
            chosen = candidates[0]
        if chosen is None:
            logger.warning("KAP search yielded no company for ticker %s", ticker_norm)
            return None

        company_id = chosen.get("memberOrFundOid") or chosen.get("companyId")
        if not company_id:
            return None

        ref = KAPCompanyRef(
            ticker=ticker_norm,
            company_id=str(company_id),
            name=normalize_visible_text(chosen.get("searchValue") or ticker_norm),
        )
        self._company_cache[ticker_norm] = ref
        return ref

    # ------------------------------------------------------------------ #
    # Disclosure listings
    # ------------------------------------------------------------------ #
    def list_disclosures_by_criteria(
        self,
        company: KAPCompanyRef,
        *,
        date_from: datetime,
        date_to: datetime,
        disclosure_class: str = "ODA",
        subject_oid: str | None = None,
    ) -> list[dict[str, Any]]:
        body = {
            "fromDate": date_from.strftime("%Y-%m-%d"),
            "toDate": date_to.strftime("%Y-%m-%d"),
            "disclosureClass": disclosure_class,
            "subjectList": [subject_oid] if subject_oid else [],
            "mkkMemberOidList": [company.company_id],
            "inactiveMkkMemberOidList": [],
            "bdkMemberOidList": [],
            "fromSrc": False,
            "disclosureIndexList": [],
        }
        response = self._request(
            "POST",
            DISCLOSURE_BY_CRITERIA_URL,
            json_body=body,
            endpoint_label=f"disclosure/byCriteria/{disclosure_class}",
        )
        if response is None:
            return []
        try:
            data = response.json()
        except Exception:  # noqa: BLE001
            return []
        if isinstance(data, dict):
            data = data.get("disclosures") or data.get("items") or []
        if not isinstance(data, list):
            return []
        return data

    def list_disclosures_by_type(
        self,
        company: KAPCompanyRef,
        *,
        disclosure_type: str,
    ) -> list[dict[str, Any]]:
        url = DISCLOSURE_BY_TYPE_URL.format(type=disclosure_type, company_id=company.company_id)
        response = self._request(
            "GET",
            url,
            endpoint_label=f"company-detail/{disclosure_type}",
        )
        if response is None:
            return []
        try:
            data = response.json()
        except Exception:  # noqa: BLE001
            return []
        if not isinstance(data, list):
            return []
        # Each entry wraps a "disclosureBasic" payload.
        return [item.get("disclosureBasic", item) for item in data if isinstance(item, dict)]

    def fetch_disclosure_html(self, disclosure_index: int | str) -> str | None:
        url = NOTIFICATION_HTML_URL.format(disclosure_index=disclosure_index)
        response = self._request("GET", url, endpoint_label="bildirim_html")
        if response is None:
            return None
        try:
            decoded = response.content.decode("utf-8", errors="strict")
        except Exception:  # noqa: BLE001
            decoded = response.text
        return repair_mojibake(decoded)

    # ------------------------------------------------------------------ #
    # Conversion to DocumentChunks
    # ------------------------------------------------------------------ #
    @staticmethod
    def _extract_body_text(html: str) -> str:
        soup = BeautifulSoup(html, "lxml")
        candidates = soup.select(
            "article, main, .content, .modal-body, .disclosure-content, .type-general, .detail-content, body"
        )
        body = ""
        for node in candidates:
            text = normalize_visible_text(node.get_text(separator=" ", strip=True))
            if len(text) > len(body):
                body = text
        return body

    @staticmethod
    def _disclosure_url(row: dict[str, Any]) -> str:
        index = row.get("disclosureIndex") or row.get("disclosureIndexNumber")
        if index:
            return NOTIFICATION_HTML_URL.format(disclosure_index=index)
        return f"{KAP_BASE}/tr/Bildirim/"

    @staticmethod
    def _row_publication(row: dict[str, Any]) -> datetime:
        for key in ("publishDate", "kapPublishDate", "createDate", "submissionDate", "publicationDate", "date"):
            value = row.get(key)
            if value:
                try:
                    return parse_date(value)
                except Exception:  # noqa: BLE001
                    continue
        return now_utc()

    @staticmethod
    def _row_title(row: dict[str, Any]) -> str:
        title = row.get("title") or row.get("subject") or row.get("disclosureSubject") or "KAP Disclosure"
        return normalize_visible_text(str(title))

    @staticmethod
    def _row_summary(row: dict[str, Any]) -> str:
        for key in ("summary", "abstract", "subject", "ozet"):
            value = row.get(key)
            if value:
                return normalize_visible_text(str(value))
        return ""

    def _row_to_raw_doc(
        self,
        row: dict[str, Any],
        company: KAPCompanyRef,
        *,
        disclosure_class: str,
    ) -> RawDoc | None:
        title = self._row_title(row)
        summary = self._row_summary(row)
        publication = self._row_publication(row)
        url = self._disclosure_url(row)
        notification_type = normalize_notification_type(
            TYPE_TO_NOTIFICATION.get(disclosure_class.upper(), "Material Event")
        )

        full_text = summary
        index = row.get("disclosureIndex") or row.get("disclosureIndexNumber")
        if index:
            html = self.fetch_disclosure_html(index)
            if html:
                body = self._extract_body_text(html)
                if len(body) > len(full_text):
                    full_text = body

        if not full_text:
            full_text = title

        institution = normalize_visible_text(
            row.get("companyName") or row.get("memberName") or company.name or "KAP"
        )

        return RawDoc(
            ticker=company.ticker,
            source_type=SourceType.KAP,
            institution=institution,
            url=url,
            title=title,
            text=full_text,
            date=publication,
            published_at=publication,
            retrieved_at=now_utc().isoformat(),
            notification_type=notification_type,
            language="tr",
            confidence=0.97,
            metadata={
                "kap_disclosure_class": disclosure_class.upper(),
                "kap_disclosure_index": str(index) if index else "",
                "kap_company_oid": company.company_id,
                "source_channel": "kap_api",
                "source_reliability": 0.95,
                "discovered_via": "kap_rest_api",
                "title": title,
            },
        )

    # ------------------------------------------------------------------ #
    # High level entry point
    # ------------------------------------------------------------------ #
    def collect_disclosures(
        self,
        ticker: str,
        *,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        disclosure_classes: tuple[str, ...] = ("ODA", "FR", "DG"),
        max_per_class: int = 25,
    ) -> list[DocumentChunk]:
        """Pull recent disclosures for ``ticker`` from the public KAP API.

        Returns an empty list if KAP refuses the request — callers can then
        fall back to ``KAPIngestor`` HTML scraping.
        """

        self.last_telemetry = self._fresh_telemetry()
        company = self.lookup_company(ticker)
        if company is None:
            self.last_telemetry["mode"] = "rest_api_no_company"
            return []

        end = date_to or now_utc()
        start = date_from or (end - timedelta(days=180))
        if start > end:
            start, end = end, start

        chunks: list[DocumentChunk] = []
        for disclosure_class in disclosure_classes:
            try:
                rows = self.list_disclosures_by_criteria(
                    company,
                    date_from=start,
                    date_to=end,
                    disclosure_class=disclosure_class,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "KAP API class=%s for %s failed: %s", disclosure_class, ticker, exc
                )
                rows = []
            for row in rows[:max_per_class]:
                raw = self._row_to_raw_doc(row, company, disclosure_class=disclosure_class)
                if raw is None:
                    continue
                produced = build_chunks(raw)
                if produced:
                    chunks.extend(produced)
                    self.last_telemetry["success_count"] = int(self.last_telemetry["success_count"]) + 1

        if chunks:
            self.last_telemetry["last_success_at"] = now_utc().isoformat()
        return chunks
