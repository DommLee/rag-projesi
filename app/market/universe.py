from __future__ import annotations

import csv
import io
import json
import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import requests

DEFAULT_BIST_UNIVERSE: list[str] = [
    "AEFES",
    "AKBNK",
    "AKSEN",
    "ALARK",
    "ARCLK",
    "ASELS",
    "ASTOR",
    "BIMAS",
    "BRYAT",
    "CCOLA",
    "CIMSA",
    "DOAS",
    "DOHOL",
    "EKGYO",
    "ENJSA",
    "ENKAI",
    "EREGL",
    "FROTO",
    "GARAN",
    "GESAN",
    "GUBRF",
    "HEKTS",
    "ISCTR",
    "KCHOL",
    "KONTR",
    "KOZAA",
    "KOZAL",
    "MGROS",
    "ODAS",
    "OTKAR",
    "OYAKC",
    "PETKM",
    "PGSUS",
    "SAHOL",
    "SASA",
    "SISE",
    "SMRTG",
    "TCELL",
    "THYAO",
    "TKFEN",
    "TOASO",
    "TSKB",
    "TUPRS",
    "ULKER",
    "VAKBN",
    "YKBNK",
    "ALFAS",
    "ENERY",
    "MAVI",
]


CORE_HIGH_PRIORITY: set[str] = {
    "AKBNK",
    "ASELS",
    "BIMAS",
    "FROTO",
    "GARAN",
    "ISCTR",
    "KCHOL",
    "SAHOL",
    "SISE",
    "TCELL",
    "THYAO",
    "TUPRS",
    "YKBNK",
}


@dataclass(slots=True)
class UniverseItem:
    ticker: str
    priority_score: float
    reason: str
    queue: str = "background"


class BISTUniverseService:
    def __init__(
        self,
        path: str | Path,
        *,
        primary_url: str = "",
        refresh_hours: int = 24,
    ) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.primary_url = primary_url.strip()
        self.refresh_hours = max(1, int(refresh_hours))
        self._session = requests.Session()
        self._session.headers.update({"User-Agent": "BIST-Agentic-RAG/2.1 Universe Module"})

        self._last_refresh_at: datetime | None = None
        self._last_refresh_source: str = "bootstrap"
        self._last_refresh_error: str = ""

        if not self.path.exists():
            self._persist_universe(DEFAULT_BIST_UNIVERSE)
        self._universe = self._load()
        self.refresh_if_needed(force=False)

    @property
    def last_refresh_at(self) -> datetime | None:
        return self._last_refresh_at

    @property
    def last_refresh_source(self) -> str:
        return self._last_refresh_source

    @property
    def last_refresh_error(self) -> str:
        return self._last_refresh_error

    @staticmethod
    def _normalize_tickers(values: Iterable[str]) -> list[str]:
        cleaned = [str(item).strip().upper() for item in values if str(item).strip()]
        return list(dict.fromkeys([item for item in cleaned if 3 <= len(item) <= 6 and item.isascii()]))

    def _load(self) -> list[str]:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                tickers = payload.get("tickers", [])
                if isinstance(tickers, list):
                    normalized = self._normalize_tickers(tickers)
                    if normalized:
                        metadata_refresh = payload.get("last_refresh_at")
                        if metadata_refresh:
                            try:
                                self._last_refresh_at = datetime.fromisoformat(metadata_refresh)
                            except Exception:  # noqa: BLE001
                                self._last_refresh_at = None
                        self._last_refresh_source = str(payload.get("source", "file"))
                        return normalized
            elif isinstance(payload, list):
                normalized = self._normalize_tickers(payload)
                if normalized:
                    return normalized
        except Exception:  # noqa: BLE001
            pass
        return DEFAULT_BIST_UNIVERSE.copy()

    def _persist_universe(self, tickers: list[str], source: str = "fallback") -> None:
        self._last_refresh_at = datetime.now(UTC)
        self._last_refresh_source = source
        payload = {
            "tickers": tickers,
            "last_refresh_at": self._last_refresh_at.isoformat(),
            "source": source,
        }
        self.path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def _parse_primary_payload(self, text: str) -> list[str]:
        raw = text.strip()
        if not raw:
            return []

        # JSON list or {"tickers":[...]}
        try:
            payload = json.loads(raw)
            if isinstance(payload, dict):
                values = payload.get("tickers", [])
                if isinstance(values, list):
                    return self._normalize_tickers(values)
            if isinstance(payload, list):
                return self._normalize_tickers(payload)
        except Exception:  # noqa: BLE001
            pass

        # CSV with symbol/ticker column.
        try:
            reader = csv.DictReader(io.StringIO(raw))
            fields = [f.lower() for f in (reader.fieldnames or [])]
            if fields:
                symbol_field = None
                for candidate in ("ticker", "symbol", "code"):
                    if candidate in fields:
                        symbol_field = candidate
                        break
                if symbol_field:
                    values = []
                    for row in reader:
                        values.append(row.get(symbol_field, ""))
                    normalized = self._normalize_tickers(values)
                    if normalized:
                        return normalized
        except Exception:  # noqa: BLE001
            pass

        # Plain text fallback.
        return self._normalize_tickers(re.findall(r"\b[A-Z]{3,6}\b", raw))

    def refresh_from_primary(self) -> list[str] | None:
        if not self.primary_url:
            self._last_refresh_error = "primary_url_not_configured"
            return None
        try:
            response = self._session.get(self.primary_url, timeout=15)
            response.raise_for_status()
            parsed = self._parse_primary_payload(response.text)
            if not parsed:
                self._last_refresh_error = "primary_payload_empty"
                return None
            self._persist_universe(parsed, source="primary")
            self._universe = parsed
            self._last_refresh_error = ""
            return parsed
        except Exception as exc:  # noqa: BLE001
            self._last_refresh_error = str(exc)[:500]
            return None

    def refresh_if_needed(self, *, force: bool = False) -> list[str]:
        if force:
            refreshed = self.refresh_from_primary()
            return refreshed or self._universe

        if self._last_refresh_at:
            if datetime.now(UTC) - self._last_refresh_at < timedelta(hours=self.refresh_hours):
                return self._universe

        refreshed = self.refresh_from_primary()
        return refreshed or self._universe

    def list_tickers(self) -> list[str]:
        return self._universe.copy()

    def reload(self) -> list[str]:
        self._universe = self._load()
        return self._universe.copy()

    @staticmethod
    def _score(
        ticker: str,
        activity_counter: dict[str, int] | None,
        last_seen_minutes: dict[str, float] | None,
        queue: str,
    ) -> UniverseItem:
        activity = float((activity_counter or {}).get(ticker, 0))
        stale_minutes = float((last_seen_minutes or {}).get(ticker, 9999.0))
        core_bonus = 5.0 if ticker in CORE_HIGH_PRIORITY else 0.0
        queue_bonus = {"hot": 9.0, "active": 4.0, "background": 1.0}.get(queue, 0.0)
        stale_bonus = min(8.0, stale_minutes / 10.0)
        score = core_bonus + queue_bonus + (activity * 0.6) + stale_bonus
        reason = f"queue={queue},core={ticker in CORE_HIGH_PRIORITY},activity={activity:.0f},stale_min={stale_minutes:.1f}"
        return UniverseItem(ticker=ticker, priority_score=round(score, 3), reason=reason, queue=queue)

    def build_queues(
        self,
        *,
        activity_counter: dict[str, int] | None = None,
        last_seen_minutes: dict[str, float] | None = None,
        hot_tickers: Iterable[str] | None = None,
        allowed: Iterable[str] | None = None,
    ) -> dict[str, list[UniverseItem]]:
        universe = self._universe
        if allowed:
            allow = {item.strip().upper() for item in allowed if item}
            universe = [ticker for ticker in universe if ticker in allow]

        hot_set = {item.strip().upper() for item in (hot_tickers or []) if item}
        queues: dict[str, list[UniverseItem]] = {"hot": [], "active": [], "background": []}

        for ticker in universe:
            activity = float((activity_counter or {}).get(ticker, 0))
            stale_minutes = float((last_seen_minutes or {}).get(ticker, 9999.0))
            if ticker in hot_set:
                queue = "hot"
            elif activity > 0 or stale_minutes < 24 * 60:
                queue = "active"
            else:
                queue = "background"
            queues[queue].append(self._score(ticker, activity_counter, last_seen_minutes, queue))

        for key in queues:
            queues[key].sort(key=lambda item: item.priority_score, reverse=True)
        return queues

    def prioritize(
        self,
        *,
        limit: int,
        activity_counter: dict[str, int] | None = None,
        last_seen_minutes: dict[str, float] | None = None,
        allowed: Iterable[str] | None = None,
        hot_tickers: Iterable[str] | None = None,
    ) -> list[UniverseItem]:
        queues = self.build_queues(
            activity_counter=activity_counter,
            last_seen_minutes=last_seen_minutes,
            hot_tickers=hot_tickers,
            allowed=allowed,
        )
        target = max(1, min(limit, sum(len(v) for v in queues.values())))

        # Balanced queue mix for full universe mode:
        # hot 50%, active 35%, background 15% (with graceful backfill).
        plan = {
            "hot": max(1, int(round(target * 0.50))),
            "active": max(1, int(round(target * 0.35))),
            "background": max(1, int(round(target * 0.15))),
        }
        selected: list[UniverseItem] = []
        for name in ("hot", "active", "background"):
            take = min(plan[name], len(queues[name]))
            selected.extend(queues[name][:take])

        if len(selected) < target:
            leftovers = []
            for name in ("hot", "active", "background"):
                leftovers.extend(queues[name][plan[name] :])
            leftovers.sort(key=lambda item: item.priority_score, reverse=True)
            selected.extend(leftovers[: target - len(selected)])

        selected.sort(key=lambda item: item.priority_score, reverse=True)
        return selected[:target]

    def coverage_stats(self, processed_tickers_24h: set[str]) -> dict:
        total = len(self._universe)
        processed = len({ticker for ticker in processed_tickers_24h if ticker in self._universe})
        ratio = 0.0 if total == 0 else round(processed / total, 4)
        return {
            "universe_size_total": total,
            "universe_processed_24h": processed,
            "ticker_coverage_ratio": ratio,
            "last_refresh_at": self._last_refresh_at.isoformat() if self._last_refresh_at else None,
            "last_refresh_source": self._last_refresh_source,
            "last_refresh_error": self._last_refresh_error,
        }

