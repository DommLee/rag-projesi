from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


DEFAULT_BIST_UNIVERSE: list[str] = [
    "AEFES",
    "AKBNK",
    "ALARK",
    "ARCLK",
    "ASELS",
    "ASTOR",
    "BIMAS",
    "DOAS",
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


class BISTUniverseService:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.path.write_text(json.dumps(DEFAULT_BIST_UNIVERSE, ensure_ascii=False, indent=2), encoding="utf-8")
        self._universe = self._load()

    def _load(self) -> list[str]:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(payload, list):
                normalized = [str(item).strip().upper() for item in payload if str(item).strip()]
                deduped = list(dict.fromkeys(normalized))
                return deduped or DEFAULT_BIST_UNIVERSE.copy()
        except Exception:
            pass
        return DEFAULT_BIST_UNIVERSE.copy()

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
    ) -> UniverseItem:
        activity = float((activity_counter or {}).get(ticker, 0))
        stale_minutes = float((last_seen_minutes or {}).get(ticker, 9999.0))
        core_bonus = 5.0 if ticker in CORE_HIGH_PRIORITY else 0.0
        stale_bonus = min(8.0, stale_minutes / 10.0)
        score = core_bonus + (activity * 0.6) + stale_bonus
        reason = f"core={ticker in CORE_HIGH_PRIORITY},activity={activity:.0f},stale_min={stale_minutes:.1f}"
        return UniverseItem(ticker=ticker, priority_score=round(score, 3), reason=reason)

    def prioritize(
        self,
        *,
        limit: int,
        activity_counter: dict[str, int] | None = None,
        last_seen_minutes: dict[str, float] | None = None,
        allowed: Iterable[str] | None = None,
    ) -> list[UniverseItem]:
        universe = self._universe
        if allowed:
            allow = {item.strip().upper() for item in allowed if item}
            universe = [ticker for ticker in universe if ticker in allow]
        scored = [self._score(ticker, activity_counter, last_seen_minutes) for ticker in universe]
        scored.sort(key=lambda item: item.priority_score, reverse=True)
        safe_limit = max(1, min(limit, len(scored)))
        return scored[:safe_limit]

