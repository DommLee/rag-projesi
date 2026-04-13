from __future__ import annotations

from datetime import UTC, datetime

import httpx

from app.config import get_settings

COIN_MAP = {
    "BTC": "bitcoin",
    "ETH": "ethereum",
    "BNB": "binancecoin",
    "SOL": "solana",
    "XRP": "ripple",
}


class CoinGeckoContextConnector:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.timeout = 15.0

    @property
    def enabled(self) -> bool:
        return bool(self.settings.crypto_context_enabled)

    def fetch_context(self, symbols: list[str] | None = None) -> dict:
        if not self.enabled:
            return {
                "key": "coingecko_context",
                "enabled": False,
                "status": "disabled",
                "fetched": 0,
                "last_success_at": None,
                "error": "crypto_context_disabled",
                "snapshot": [],
            }
        tokens = [item.strip().upper() for item in (symbols or ["BTC", "ETH"]) if item.strip()]
        ids = [COIN_MAP.get(token, token.lower()) for token in tokens]
        url = f"{self.settings.coingecko_base_url.rstrip('/')}/coins/markets"
        params = {"vs_currency": "usd", "ids": ",".join(ids), "price_change_percentage": "24h"}
        headers = {}
        if self.settings.coingecko_api_key.strip():
            headers["x-cg-pro-api-key"] = self.settings.coingecko_api_key.strip()
        try:
            response = httpx.get(url, params=params, headers=headers, timeout=self.timeout)
            response.raise_for_status()
            rows = response.json()
            snapshot = [
                {
                    "symbol": str(row.get("symbol", "")).upper(),
                    "name": row.get("name") or "",
                    "price_usd": row.get("current_price"),
                    "change_pct_24h": row.get("price_change_percentage_24h"),
                    "market_cap_rank": row.get("market_cap_rank"),
                    "provider": "coingecko",
                    "last_updated": row.get("last_updated") or datetime.now(UTC).isoformat(),
                }
                for row in rows
            ]
            return {
                "key": "coingecko_context",
                "enabled": True,
                "status": "ok",
                "fetched": len(snapshot),
                "last_success_at": datetime.now(UTC).isoformat() if snapshot else None,
                "error": "",
                "snapshot": snapshot,
            }
        except Exception as exc:  # noqa: BLE001
            return {
                "key": "coingecko_context",
                "enabled": True,
                "status": "error",
                "fetched": 0,
                "last_success_at": None,
                "error": str(exc),
                "snapshot": [],
            }
