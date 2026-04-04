from __future__ import annotations

import time
import urllib.parse
import urllib.robotparser
from collections import defaultdict
from dataclasses import dataclass

import requests

from app.config import get_settings


@dataclass
class CrawlDecision:
    allowed: bool
    reason: str


class LegalSafeCrawlerPolicy:
    def __init__(self) -> None:
        self.settings = get_settings()
        self._last_request_by_domain: dict[str, float] = defaultdict(float)
        self._robots_cache: dict[str, urllib.robotparser.RobotFileParser] = {}
        self._session = requests.Session()
        self._session.headers.update({"User-Agent": self.settings.crawler_user_agent})

    @staticmethod
    def _domain(url: str) -> str:
        return urllib.parse.urlparse(url).netloc.lower()

    def _load_robots(self, domain: str) -> urllib.robotparser.RobotFileParser:
        if domain in self._robots_cache:
            return self._robots_cache[domain]

        parser = urllib.robotparser.RobotFileParser()
        robots_url = f"https://{domain}/robots.txt"
        try:
            parser.set_url(robots_url)
            parser.read()
        except Exception:  # noqa: BLE001
            # If robots cannot be fetched, allow but keep reason visible.
            parser = urllib.robotparser.RobotFileParser()
            parser.parse(["User-agent: *", "Allow: /"])
        self._robots_cache[domain] = parser
        return parser

    def decide(self, url: str) -> CrawlDecision:
        domain = self._domain(url)
        parser = self._load_robots(domain)
        allowed = parser.can_fetch(self.settings.crawler_user_agent, url)
        if not allowed:
            return CrawlDecision(allowed=False, reason=f"robots_disallow:{domain}")
        return CrawlDecision(allowed=True, reason="allowed")

    def wait_rate_limit(self, url: str, custom_seconds: float | None = None) -> None:
        domain = self._domain(url)
        min_wait = custom_seconds if custom_seconds is not None else self.settings.crawler_default_rate_limit_seconds
        elapsed = time.time() - self._last_request_by_domain[domain]
        if elapsed < min_wait:
            time.sleep(min_wait - elapsed)
        self._last_request_by_domain[domain] = time.time()

