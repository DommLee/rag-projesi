"""Lightweight web search wrapper.

Supports Tavily (preferred) with a DuckDuckGo HTML fallback so the agent
can fetch live context even when no paid API key is configured.
"""

from __future__ import annotations

import logging
import re

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)

_HEADERS = {
    "User-Agent": "BIST-Agentic-RAG/2.3 (+Academic Research)",
    "Accept-Language": "tr-TR,tr;q=0.9,en;q=0.5",
}


def _tavily_search(query: str, *, max_results: int = 5) -> list[dict[str, str]]:
    settings = get_settings()
    resp = httpx.post(
        "https://api.tavily.com/search",
        json={
            "api_key": settings.tavily_api_key,
            "query": query,
            "max_results": max_results,
            "search_depth": "basic",
            "include_answer": False,
        },
        timeout=12.0,
    )
    resp.raise_for_status()
    data = resp.json()
    return [
        {
            "title": item.get("title", ""),
            "url": item.get("url", ""),
            "snippet": item.get("content", "")[:300],
        }
        for item in data.get("results", [])[:max_results]
    ]


def _ddg_html_search(query: str, *, max_results: int = 5) -> list[dict[str, str]]:
    """Minimal DuckDuckGo HTML scrape — no API key required."""
    resp = httpx.get(
        "https://html.duckduckgo.com/html/",
        params={"q": query},
        headers=_HEADERS,
        timeout=10.0,
        follow_redirects=True,
    )
    resp.raise_for_status()
    results: list[dict[str, str]] = []
    # Parse result blocks from the HTML response
    for match in re.finditer(
        r'class="result__a"[^>]*href="(?P<url>[^"]+)"[^>]*>(?P<title>.*?)</a>'
        r'.*?class="result__snippet"[^>]*>(?P<snippet>.*?)</',
        resp.text,
        re.DOTALL,
    ):
        url = match.group("url")
        # DuckDuckGo wraps URLs in a redirect — extract the real URL
        real_url_match = re.search(r"uddg=([^&]+)", url)
        if real_url_match:
            from urllib.parse import unquote
            url = unquote(real_url_match.group(1))
        title = re.sub(r"<[^>]+>", "", match.group("title")).strip()
        snippet = re.sub(r"<[^>]+>", "", match.group("snippet")).strip()
        if title and url:
            results.append({"title": title, "url": url, "snippet": snippet[:300]})
        if len(results) >= max_results:
            break
    return results


def web_search(query: str, max_results: int = 5) -> list[dict[str, str]]:
    """Search the web. Uses Tavily if key is set, otherwise DuckDuckGo HTML."""
    settings = get_settings()
    if not settings.web_search_enabled:
        return []
    if settings.tavily_api_key.strip():
        try:
            return _tavily_search(query, max_results=max_results)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Tavily search failed, falling back to DDG: %s", exc)
    try:
        return _ddg_html_search(query, max_results=max_results)
    except Exception as exc:  # noqa: BLE001
        logger.warning("DuckDuckGo search failed: %s", exc)
        return []
