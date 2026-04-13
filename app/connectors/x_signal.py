from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime

import httpx

from app.config import get_settings
from app.market.entity_aliases import alias_keywords
from app.utils.text import normalize_visible_text

STOPWORDS = {
    "borsa",
    "hisse",
    "şirket",
    "sirket",
    "turkiye",
    "türkiye",
    "bist",
    "ile",
    "icin",
    "için",
    "gibi",
}


class XSignalConnector:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.timeout = 20.0

    @property
    def enabled(self) -> bool:
        return bool(self.settings.x_api_bearer_token.strip())

    def _query(self, ticker: str) -> str:
        aliases = alias_keywords(ticker)[:4]
        terms = " OR ".join([f'"{ticker.upper()}"', *[f'"{alias}"' for alias in aliases if alias.upper() != ticker.upper()]])
        return f"({terms}) lang:tr -is:retweet"

    @staticmethod
    def _extract_theme_buckets(texts: list[str], aliases: list[str]) -> list[dict]:
        bucket = Counter()
        alias_set = {item.lower() for item in aliases}
        for text in texts:
            for raw in normalize_visible_text(text).split():
                token = "".join(ch for ch in raw.lower() if ch.isalnum())
                if len(token) < 4 or token in STOPWORDS or token in alias_set:
                    continue
                bucket[token] += 1
        return [{"label": label, "value": value} for label, value in bucket.most_common(6)]

    def fetch_signal(self, ticker: str, max_results: int = 20) -> dict:
        if not self.enabled:
            return {
                "key": "x_signal",
                "enabled": False,
                "status": "disabled",
                "fetched": 0,
                "last_success_at": None,
                "error": "x_api_bearer_token_missing",
                "snapshot": {},
            }

        url = f"{self.settings.x_api_base_url.rstrip('/')}/tweets/search/recent"
        aliases = [ticker.upper(), *alias_keywords(ticker)]
        params = {
            "query": self._query(ticker),
            "max_results": max(10, min(100, max_results)),
            "tweet.fields": "created_at,public_metrics,author_id,text",
            "expansions": "author_id",
            "user.fields": "username,verified,name",
        }
        headers = {"Authorization": f"Bearer {self.settings.x_api_bearer_token.strip()}"}
        try:
            response = httpx.get(url, params=params, headers=headers, timeout=self.timeout)
            response.raise_for_status()
            payload = response.json()
            rows = payload.get("data", []) or []
            includes = payload.get("includes", {}) or {}
            users = {item.get("id"): item for item in includes.get("users", []) or []}
            texts = [item.get("text", "") for item in rows]
            engagement_sum = 0
            verified_count = 0
            handles = Counter()
            for item in rows:
                metrics = item.get("public_metrics", {}) or {}
                engagement_sum += int(metrics.get("like_count", 0)) + int(metrics.get("retweet_count", 0)) + int(metrics.get("reply_count", 0))
                user = users.get(item.get("author_id"), {})
                if user.get("verified"):
                    verified_count += 1
                username = normalize_visible_text(user.get("username") or "")
                if username:
                    handles[username] += 1
            now_iso = datetime.now(UTC).isoformat()
            post_count = len(rows)
            snapshot = {
                "post_count": post_count,
                "engagement_sum": engagement_sum,
                "verified_author_ratio": round(verified_count / max(1, post_count), 4),
                "unique_author_count": len({item.get("author_id") for item in rows if item.get("author_id")}),
                "high_confidence_handles": [{"handle": handle, "count": count} for handle, count in handles.most_common(5)],
                "theme_buckets": self._extract_theme_buckets(texts, aliases),
                "social_confidence": round(min(0.8, (post_count / 50.0) + (verified_count / max(1, post_count)) * 0.3), 4),
                "query": params["query"],
            }
            return {
                "key": "x_signal",
                "enabled": True,
                "status": "ok",
                "fetched": post_count,
                "last_success_at": now_iso if post_count else None,
                "error": "",
                "snapshot": snapshot,
            }
        except Exception as exc:  # noqa: BLE001
            return {
                "key": "x_signal",
                "enabled": True,
                "status": "error",
                "fetched": 0,
                "last_success_at": None,
                "error": str(exc),
                "snapshot": {},
            }
