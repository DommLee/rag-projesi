from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime

import requests
from bs4 import BeautifulSoup

from app.ingestion.policy import LegalSafeCrawlerPolicy
from app.market.entity_aliases import alias_keywords, entity_match_details
from app.utils.text import normalize_visible_text, repair_mojibake
from app.utils.web_search import web_search


class WebResearchConnector:
    def __init__(self) -> None:
        self.timeout = 12.0
        self.policy = LegalSafeCrawlerPolicy()
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": self.policy.settings.crawler_user_agent,
                "Accept-Language": "tr-TR,tr;q=0.9,en;q=0.7",
            }
        )

    @property
    def enabled(self) -> bool:
        return True

    @staticmethod
    def _queries(ticker: str) -> list[str]:
        aliases = [alias for alias in alias_keywords(ticker) if len(alias) > 2][:3]
        base = [
            f"{ticker} BIST KAP haber",
            f"{ticker} finansal sonuçlar KAP",
            f"{ticker} aracı kurum raporu",
            f"{ticker} bilanço özel durum açıklaması",
            f"site:kap.org.tr/tr/Bildirim {ticker}",
            f"site:bloomberght.com {ticker} hisse",
            f"site:aa.com.tr ekonomi {ticker}",
            f"site:ekonomim.com {ticker} şirket haber",
            f"site:bigpara.hurriyet.com.tr {ticker} borsa",
            f"site:paraanaliz.com {ticker} hisse",
            f"site:dunya.com {ticker} ekonomi",
            f"site:foreks.com {ticker} haber",
            f"site:tr.investing.com {ticker} hisse",
        ]
        for alias in aliases:
            base.append(f"\"{alias}\" hisse borsa haber")
            base.append(f"\"{alias}\" KAP finansal sonuçlar")
        return list(dict.fromkeys(base))

    @staticmethod
    def _source_reliability(url: str) -> float:
        host = url.lower()
        if "kap.org.tr" in host:
            return 1.0
        if "borsaistanbul.com" in host or "evds2.tcmb.gov.tr" in host:
            return 0.95
        if "aa.com.tr" in host or "bloomberght.com" in host or "ekonomim.com" in host:
            return 0.72
        if "foreks.com" in host or "dunya.com" in host:
            return 0.7
        if "bigpara.hurriyet.com.tr" in host or "paraanaliz.com" in host or "investing.com" in host:
            return 0.66
        if "mynet.com" in host or "haberturk.com" in host or "sozcu.com.tr" in host:
            return 0.62
        return 0.55

    @staticmethod
    def _theme_buckets(rows: list[dict]) -> list[dict]:
        counter: Counter[str] = Counter()
        for row in rows:
            text = normalize_visible_text(
                f"{row.get('title', '')} {row.get('snippet', '')} {row.get('article_preview', '')}"
            )
            for token in text.split():
                cleaned = "".join(ch for ch in token.lower() if ch.isalnum())
                if len(cleaned) >= 5:
                    counter[cleaned] += 1
        return [{"label": label, "value": value} for label, value in counter.most_common(8)]

    def _scrape_article_preview(self, url: str, ticker: str) -> tuple[dict, dict]:
        stats = {"attempted": 1, "scraped": 0, "blocked": 0, "error": ""}
        decision = self.policy.decide(url)
        if not decision.allowed:
            stats["blocked"] = 1
            stats["error"] = decision.reason
            return {}, stats
        try:
            self.policy.wait_rate_limit(url)
            response = self.session.get(url, timeout=self.timeout)
            response.raise_for_status()
            html = repair_mojibake(response.text)
        except Exception as exc:  # noqa: BLE001
            stats["error"] = str(exc)[:160]
            return {}, stats

        soup = BeautifulSoup(html, "lxml")
        title = normalize_visible_text(soup.title.string if soup.title else "")
        body = ""
        for node in soup.select("article, main, .article, .article-content, .news-content, .content, body"):
            candidate = normalize_visible_text(node.get_text(" ", strip=True))
            if len(candidate) > len(body):
                body = candidate
        if not body:
            stats["error"] = "empty_article_body"
            return {}, stats

        details = entity_match_details(f"{title} {body[:1200]}", ticker, title=title, source_label=url)
        score = float(details.get("score", 0.0))
        if score < 0.34:
            stats["error"] = f"article_entity_mismatch:{details.get('reason', '')}"
            return {}, stats

        stats["scraped"] = 1
        return {
            "article_title": title[:240],
            "article_preview": body[:900],
            "scraped_at": datetime.now(UTC).isoformat(),
            "scraper_status": "ok",
            "article_entity_score": score,
            "article_entity_reason": details.get("reason", ""),
        }, stats

    def fetch_context(self, ticker: str, *, max_results: int = 8) -> dict:
        queries = self._queries(ticker.upper())
        accepted: list[dict] = []
        rejected: list[dict] = []
        seen_urls: set[str] = set()
        scraper_stats = {"attempted": 0, "scraped": 0, "blocked": 0, "errors": 0}

        for query in queries:
            for item in web_search(query, max_results=max_results):
                title = normalize_visible_text(item.get("title", ""))
                snippet = normalize_visible_text(item.get("snippet", ""))
                url = normalize_visible_text(item.get("url", ""))
                if not url or url in seen_urls:
                    continue
                seen_urls.add(url)
                details = entity_match_details(
                    f"{title} {snippet}",
                    ticker,
                    title=title,
                    source_label=url,
                )
                score = float(details.get("score", 0.0))
                row = {
                    "title": title[:240] or f"{ticker} web context",
                    "snippet": snippet[:320],
                    "url": url,
                    "query": query,
                    "entity_score": score,
                    "entity_reason": details.get("reason", ""),
                    "source_reliability": self._source_reliability(url),
                }
                if score >= 0.34:
                    accepted.append(row)
                else:
                    if len(rejected) < 12:
                        rejected.append(row)

        accepted.sort(
            key=lambda row: (float(row.get("entity_score", 0.0)), float(row.get("source_reliability", 0.0))),
            reverse=True,
        )
        enriched: list[dict] = []
        for row in accepted[: min(max_results, 6)]:
            article_data, stats = self._scrape_article_preview(str(row.get("url", "")), ticker)
            scraper_stats["attempted"] += int(stats.get("attempted", 0))
            scraper_stats["scraped"] += int(stats.get("scraped", 0))
            scraper_stats["blocked"] += int(stats.get("blocked", 0))
            if int(stats.get("blocked", 0)):
                row["scraper_error"] = stats.get("error", "blocked")
                row["scraper_status"] = "blocked"
            elif stats.get("error"):
                scraper_stats["errors"] += 1
                row["scraper_error"] = stats["error"]
                row["scraper_status"] = "skipped"
            row.update(article_data)
            enriched.append(row)
        if len(accepted) > len(enriched):
            enriched.extend(accepted[len(enriched):])
        now_iso = datetime.now(UTC).isoformat()
        return {
            "key": "web_search_context",
            "enabled": True,
            "status": "ok" if accepted else "idle",
            "fetched": len(accepted),
            "accepted_count": len(accepted),
            "rejected_entity": len(rejected),
            "blocked": scraper_stats["blocked"],
            "last_success_at": now_iso if accepted else None,
            "error": "",
            "snapshot": {
                "queries": queries,
                "items": enriched[: max_results * 2],
                "theme_buckets": self._theme_buckets(enriched),
                "scraper_stats": scraper_stats,
            },
            "scraper_stats": scraper_stats,
            "rejected_samples": [
                {
                    "title": row["title"],
                    "source": row["url"],
                    "score": row["entity_score"],
                    "reason": row["entity_reason"],
                }
                for row in rejected
            ],
        }
