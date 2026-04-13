from __future__ import annotations

import csv
import io
import logging
import threading
from dataclasses import dataclass
from datetime import UTC, datetime

import requests


logger = logging.getLogger(__name__)

try:
    import yfinance as yf
except Exception:  # noqa: BLE001
    yf = None


@dataclass(slots=True)
class PricePoint:
    ticker: str
    price: float | None
    change_pct: float | None
    currency: str
    market_time: datetime
    provider: str
    stale: bool
    note: str = ""


@dataclass(slots=True)
class _CacheEntry:
    point: PricePoint
    updated_at: datetime


class MarketPriceService:
    def __init__(self, ttl_seconds: int = 60) -> None:
        self.ttl_seconds = ttl_seconds
        self._cache: dict[str, _CacheEntry] = {}
        self._history: dict[str, list[tuple[datetime, float]]] = {}
        self._lock = threading.Lock()
        self._session = requests.Session()
        self._session.headers.update({"User-Agent": "BIST-Agentic-RAG/2.0 Market Module"})

    @staticmethod
    def _to_symbol(ticker: str) -> str:
        base = ticker.strip().upper()
        if base.endswith(".IS"):
            return base
        return f"{base}.IS"

    def _fetch_yahoo(self, ticker: str) -> PricePoint:
        if yf is None:
            raise RuntimeError("yfinance_not_installed")
        symbol = self._to_symbol(ticker)
        stock = yf.Ticker(symbol)
        info = stock.fast_info or {}
        price_raw = (
            info.get("lastPrice")
            or info.get("last_price")
            or info.get("regularMarketPrice")
            or info.get("regular_market_price")
        )
        prev_raw = info.get("previousClose") or info.get("previous_close")
        if price_raw is None:
            raise RuntimeError("yahoo_price_missing")
        price = float(price_raw)
        prev = float(prev_raw) if prev_raw else 0.0
        change_pct = ((price - prev) / prev * 100.0) if prev else None
        market_time = info.get("lastTradeDate")
        if isinstance(market_time, datetime):
            ts = market_time.astimezone(UTC) if market_time.tzinfo else market_time.replace(tzinfo=UTC)
        else:
            ts = datetime.now(UTC)
        currency = str(info.get("currency") or "TRY")
        return PricePoint(
            ticker=ticker.upper(),
            price=round(price, 4),
            change_pct=None if change_pct is None else round(change_pct, 4),
            currency=currency,
            market_time=ts,
            provider="yahoo",
            stale=False,
        )

    def _fetch_stooq(self, ticker: str) -> PricePoint:
        symbol = self._to_symbol(ticker).lower()
        url = f"https://stooq.com/q/l/?s={symbol}&f=sd2t2ohlcv&h&e=csv"
        response = self._session.get(url, timeout=8)
        response.raise_for_status()
        reader = csv.DictReader(io.StringIO(response.text))
        row = next(reader, None)
        if not row:
            raise RuntimeError("stooq_empty")
        close_raw = (row.get("Close") or "").strip()
        if not close_raw or close_raw == "N/D":
            raise RuntimeError("stooq_no_data")
        price = float(close_raw.replace(",", "."))
        date_raw = (row.get("Date") or "").strip()
        time_raw = (row.get("Time") or "").strip()
        ts = datetime.now(UTC)
        if date_raw:
            try:
                if time_raw:
                    ts = datetime.fromisoformat(f"{date_raw}T{time_raw}").replace(tzinfo=UTC)
                else:
                    ts = datetime.fromisoformat(f"{date_raw}T00:00:00").replace(tzinfo=UTC)
            except Exception:
                ts = datetime.now(UTC)
        return PricePoint(
            ticker=ticker.upper(),
            price=round(price, 4),
            change_pct=None,
            currency="TRY",
            market_time=ts,
            provider="stooq",
            stale=False,
        )

    def _cache_get(self, ticker: str) -> _CacheEntry | None:
        key = ticker.upper()
        entry = self._cache.get(key)
        if not entry:
            return None
        age = (datetime.now(UTC) - entry.updated_at).total_seconds()
        if age <= self.ttl_seconds:
            return entry
        return None

    def _cache_put(self, point: PricePoint) -> None:
        self._cache[point.ticker] = _CacheEntry(point=point, updated_at=datetime.now(UTC))
        if point.price is not None:
            history = self._history.setdefault(point.ticker, [])
            history.append((point.market_time, float(point.price)))
            if len(history) > 48:
                del history[:-48]

    def _history_points(self, ticker: str) -> list[dict[str, str | float]]:
        history = self._history.get(ticker.upper(), [])
        return [{"ts": ts.isoformat(), "price": price} for ts, price in history[-24:]]

    def _cached_stale_point(self, ticker: str, reason: str) -> PricePoint | None:
        entry = self._cache.get(ticker.upper())
        if not entry:
            return None
        point = entry.point
        return PricePoint(
            ticker=point.ticker,
            price=point.price,
            change_pct=point.change_pct,
            currency=point.currency,
            market_time=point.market_time,
            provider="cache",
            stale=True,
            note=reason,
        )

    def get_price(self, ticker: str, force_refresh: bool = False) -> PricePoint:
        normalized = ticker.strip().upper()
        with self._lock:
            if not force_refresh:
                cached = self._cache_get(normalized)
                if cached:
                    return cached.point
            errors: list[str] = []
            for fetcher in (self._fetch_yahoo, self._fetch_stooq):
                try:
                    point = fetcher(normalized)
                    self._cache_put(point)
                    return point
                except Exception as exc:  # noqa: BLE001
                    errors.append(f"{fetcher.__name__}:{exc}")
                    continue
            stale = self._cached_stale_point(normalized, ";".join(errors))
            if stale:
                return stale
            logger.warning("Price fetch failed for %s (%s)", normalized, ";".join(errors))
            return PricePoint(
                ticker=normalized,
                price=None,
                change_pct=None,
                currency="TRY",
                market_time=datetime.now(UTC),
                provider="unavailable",
                stale=True,
                note=";".join(errors)[:500],
            )

    def get_prices(self, tickers: list[str], force_refresh: bool = False) -> dict:
        now = datetime.now(UTC)
        rows = [self.get_price(ticker, force_refresh=force_refresh) for ticker in tickers]
        providers = {row.provider for row in rows}
        return {
            "as_of": now.isoformat(),
            "count": len(rows),
            "providers_used": sorted(providers),
            "prices": [
                {
                    "ticker": row.ticker,
                    "price": row.price,
                    "change_pct": row.change_pct,
                    "currency": row.currency,
                    "market_time": row.market_time.isoformat(),
                    "provider": row.provider,
                    "stale": row.stale,
                    "note": row.note,
                    "sparkline_points": self._history_points(row.ticker),
                    "refresh_age_seconds": int(max(0.0, (now - row.market_time).total_seconds())),
                }
                for row in rows
            ],
        }
