from __future__ import annotations

from datetime import UTC, datetime

import httpx

from app.config import get_settings


class BinanceSpotContextConnector:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.timeout = 12.0

    @property
    def enabled(self) -> bool:
        return bool(self.settings.crypto_context_enabled)

    def fetch_context(self, symbols: list[str] | None = None) -> dict:
        if not self.enabled:
            return {
                "key": "binance_spot_context",
                "enabled": False,
                "status": "disabled",
                "fetched": 0,
                "last_success_at": None,
                "error": "crypto_context_disabled",
                "snapshot": [],
            }
        tokens = [item.strip().upper() for item in (symbols or ["BTC", "ETH"]) if item.strip()]
        snapshot = []
        errors = []
        for token in tokens:
            symbol = f"{token}USDT"
            url = f"{self.settings.binance_spot_base_url.rstrip('/')}/ticker/24hr"
            try:
                response = httpx.get(url, params={"symbol": symbol}, timeout=self.timeout)
                response.raise_for_status()
                row = response.json()
                snapshot.append(
                    {
                        "symbol": token,
                        "pair": symbol,
                        "price_usd": float(row.get("lastPrice")) if row.get("lastPrice") is not None else None,
                        "change_pct_24h": float(row.get("priceChangePercent")) if row.get("priceChangePercent") is not None else None,
                        "quote_volume": float(row.get("quoteVolume")) if row.get("quoteVolume") is not None else None,
                        "provider": "binance",
                        "last_updated": datetime.now(UTC).isoformat(),
                    }
                )
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{symbol}:{exc}")
        return {
            "key": "binance_spot_context",
            "enabled": True,
            "status": "ok" if snapshot else "error",
            "fetched": len(snapshot),
            "last_success_at": datetime.now(UTC).isoformat() if snapshot else None,
            "error": ";".join(errors)[:500],
            "snapshot": snapshot,
        }
