from __future__ import annotations

import logging

from app.schemas import QueryResponse

logger = logging.getLogger(__name__)


class RedisQueryCache:
    def __init__(self, redis_url: str, ttl_seconds: int = 3600, prefix: str = "bist:query") -> None:
        self.redis_url = redis_url
        self.ttl_seconds = ttl_seconds
        self.prefix = prefix
        self.enabled = False
        self._client = None
        if not redis_url:
            return
        try:
            import redis

            self._client = redis.Redis.from_url(redis_url, decode_responses=True)
            self._client.ping()
            self.enabled = True
        except Exception as exc:  # noqa: BLE001
            logger.info("Redis query cache disabled: %s", exc)
            self._client = None

    def _key(self, key: str) -> str:
        return f"{self.prefix}:{key}"

    def get(self, key: str) -> QueryResponse | None:
        if not self.enabled or self._client is None:
            return None
        try:
            raw = self._client.get(self._key(key))
            if not raw:
                return None
            return QueryResponse.model_validate_json(raw)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Redis query cache get failed: %s", exc)
            return None

    def set(self, key: str, value: QueryResponse) -> None:
        if not self.enabled or self._client is None:
            return
        try:
            self._client.setex(self._key(key), self.ttl_seconds, value.model_dump_json())
        except Exception as exc:  # noqa: BLE001
            logger.warning("Redis query cache set failed: %s", exc)

    def clear(self) -> int:
        if not self.enabled or self._client is None:
            return 0
        try:
            keys = list(self._client.scan_iter(match=f"{self.prefix}:*"))
            if not keys:
                return 0
            return int(self._client.delete(*keys))
        except Exception as exc:  # noqa: BLE001
            logger.warning("Redis query cache clear failed: %s", exc)
            return 0

    def size(self) -> int:
        if not self.enabled or self._client is None:
            return 0
        try:
            return sum(1 for _ in self._client.scan_iter(match=f"{self.prefix}:*"))
        except Exception as exc:  # noqa: BLE001
            logger.warning("Redis query cache size failed: %s", exc)
            return 0
