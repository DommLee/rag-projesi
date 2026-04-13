from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime

import httpx

from app.config import get_settings
from app.market.entity_aliases import alias_keywords, entity_match_details
from app.utils.text import normalize_visible_text


class PremiumNewsConnector:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.timeout = 20.0

    @property
    def eventregistry_enabled(self) -> bool:
        return bool(self.settings.eventregistry_api_key.strip())

    @property
    def newsapi_enabled(self) -> bool:
        return bool(self.settings.newsapi_ai_key.strip())

    def _query_terms(self, ticker: str) -> str:
        aliases = alias_keywords(ticker)
        terms = [ticker.upper(), *aliases]
        deduped = list(dict.fromkeys([item for item in terms if item]))
        return " OR ".join(deduped[:6])

    @staticmethod
    def _article_rows(payload: dict) -> list[dict]:
        articles = payload.get("articles")
        if isinstance(articles, dict):
            return articles.get("results", []) or articles.get("articles", []) or []
        if isinstance(articles, list):
            return articles
        results = payload.get("results")
        if isinstance(results, list):
            return results
        return []

    def _fetch_eventregistry(self, ticker: str, limit: int) -> dict:
        query = self._query_terms(ticker)
        response = httpx.post(
            "https://eventregistry.org/api/v1/article/getArticles",
            json={
                "action": "getArticles",
                "keyword": query,
                "articlesPage": 1,
                "articlesCount": limit,
                "articlesSortBy": "date",
                "apiKey": self.settings.eventregistry_api_key.strip(),
            },
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json()

    def _fetch_newsapi_ai(self, ticker: str, limit: int) -> dict:
        query = self._query_terms(ticker)
        response = httpx.post(
            "https://newsapi.ai/api/v1/article/getArticles",
            json={
                "action": "getArticles",
                "keyword": query,
                "articlesPage": 1,
                "articlesCount": limit,
                "articlesSortBy": "date",
                "apiKey": self.settings.newsapi_ai_key.strip(),
            },
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json()

    def fetch_candidates(self, ticker: str, limit: int = 8) -> dict:
        provider = ""
        if self.eventregistry_enabled:
            provider = "eventregistry"
            fetcher = self._fetch_eventregistry
        elif self.newsapi_enabled:
            provider = "newsapi_ai"
            fetcher = self._fetch_newsapi_ai
        else:
            return {
                "key": "premium_news",
                "provider": "disabled",
                "enabled": False,
                "status": "disabled",
                "fetched": 0,
                "last_success_at": None,
                "error": "premium_news_keys_missing",
                "articles": [],
            }

        try:
            payload = fetcher(ticker, limit)
            rows = []
            rejected = 0
            rejected_samples = []
            for article in self._article_rows(payload):
                title = normalize_visible_text(article.get("title") or article.get("body") or "")
                summary = normalize_visible_text(article.get("body") or article.get("summary") or article.get("snippet") or "")
                source = article.get("source", {})
                source_title = normalize_visible_text(source.get("title") if isinstance(source, dict) else source or provider)
                details = entity_match_details(f"{title} {summary}", ticker, title=title, source_label=source_title)
                score = float(details.get("score", 0.0))
                if score < self.settings.entity_match_threshold:
                    rejected += 1
                    if len(rejected_samples) < 12:
                        rejected_samples.append(
                            {
                                "title": title[:140] or f"{ticker} premium news",
                                "source": source_title or provider,
                                "score": score,
                                "reason": details.get("reason", "rejected"),
                            }
                        )
                    continue
                rows.append(
                    {
                        "title": title[:240] or f"{ticker} premium news",
                        "text": summary[:1200] or title,
                        "url": article.get("url") or article.get("uri") or "",
                        "institution": normalize_visible_text(source_title or provider),
                        "author": normalize_visible_text(article.get("authorName") or article.get("author") or ""),
                        "published_at": article.get("date") or article.get("publishedAt") or datetime.now(UTC).isoformat(),
                        "source_channel": "media",
                        "source_reliability": 0.8,
                        "discovered_via": provider,
                        "entity_score": score,
                        "entity_reason": details.get("reason", ""),
                    }
                )
            now_iso = datetime.now(UTC).isoformat()
            return {
                "key": provider,
                "provider": provider,
                "enabled": True,
                "status": "ok",
                "fetched": len(rows),
                "rejected_entity": rejected,
                "accepted_count": len(rows),
                "rejected_samples": rejected_samples,
                "last_success_at": now_iso if rows else None,
                "error": "",
                "articles": rows,
            }
        except Exception as exc:  # noqa: BLE001
            return {
                "key": provider,
                "provider": provider,
                "enabled": True,
                "status": "error",
                "fetched": 0,
                "rejected_entity": 0,
                "last_success_at": None,
                "error": str(exc),
                "articles": [],
            }

    @staticmethod
    def theme_snapshot(articles: list[dict]) -> list[dict]:
        bucket = Counter()
        for article in articles:
            text = normalize_visible_text(article.get("title") or "")
            for token in text.split():
                cleaned = token.lower()
                cleaned = "".join(ch for ch in cleaned if ch.isalnum())
                if len(cleaned) >= 4:
                    bucket[cleaned] += 1
        return [{"label": label, "value": count} for label, count in bucket.most_common(6)]
