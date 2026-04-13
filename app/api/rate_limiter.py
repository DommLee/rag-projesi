from __future__ import annotations

import time
from collections import defaultdict, deque
from dataclasses import dataclass

from fastapi import Request
from fastapi.responses import JSONResponse


@dataclass(frozen=True)
class RateLimitRule:
    limit: int
    window_seconds: int


class InMemoryRateLimiter:
    """Small IP+route rate limiter for local/demo use.

    It intentionally avoids an external dependency. For multi-worker production,
    swap this for a Redis-backed limiter.
    """

    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._rules = {
            "query": RateLimitRule(limit=30, window_seconds=60),
            "ingest": RateLimitRule(limit=10, window_seconds=60),
            "eval": RateLimitRule(limit=2, window_seconds=60),
        }

    def _bucket(self, path: str) -> str | None:
        if path.startswith("/v1/query"):
            return "query"
        if path.startswith("/v1/ingest"):
            return "ingest"
        if path.startswith("/v1/eval/run"):
            return "eval"
        return None

    def check(self, request: Request) -> tuple[bool, dict[str, str]]:
        bucket = self._bucket(request.url.path)
        if not bucket:
            return True, {}
        rule = self._rules[bucket]
        client = request.client.host if request.client else "unknown"
        token = request.headers.get("x-api-token") or request.query_params.get("token") or ""
        key = f"{bucket}:{client}:{token[:12]}"
        now = time.monotonic()
        hits = self._hits[key]
        while hits and now - hits[0] > rule.window_seconds:
            hits.popleft()
        remaining = max(0, rule.limit - len(hits))
        headers = {
            "X-RateLimit-Limit": str(rule.limit),
            "X-RateLimit-Remaining": str(max(0, remaining - 1)),
            "X-RateLimit-Window": str(rule.window_seconds),
        }
        if len(hits) >= rule.limit:
            retry_after = max(1, int(rule.window_seconds - (now - hits[0])))
            headers["Retry-After"] = str(retry_after)
            return False, headers
        hits.append(now)
        return True, headers


rate_limiter = InMemoryRateLimiter()


async def rate_limit_middleware(request: Request, call_next):
    ok, headers = rate_limiter.check(request)
    if not ok:
        return JSONResponse(
            status_code=429,
            content={"detail": "Rate limit exceeded. Please retry after the indicated window."},
            headers=headers,
        )
    response = await call_next(request)
    for key, value in headers.items():
        response.headers[key] = value
    return response
