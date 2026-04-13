from __future__ import annotations

from datetime import UTC, datetime

import httpx

from app.config import get_settings

DEFAULT_EVDS_SERIES = {
    "usd_try": "TP.DK.USD.A.YTL",
    "eur_try": "TP.DK.EUR.A.YTL",
}


class TCMBMacroConnector:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.base_url = "https://evds2.tcmb.gov.tr/service/evds/series="
        self.timeout = 20.0

    @property
    def enabled(self) -> bool:
        return bool(self.settings.tcmb_evds_api_key.strip())

    @staticmethod
    def _normalize_date(value: str | None) -> str:
        if not value:
            return datetime.now(UTC).date().isoformat()
        return str(value)

    def _series_map(self, series: dict[str, str] | None = None) -> dict[str, str]:
        if series:
            return series
        configured = {}
        raw = self.settings.tcmb_evds_series_csv.strip()
        if raw:
            for item in raw.split(","):
                if ":" not in item:
                    continue
                label, code = item.split(":", 1)
                label = label.strip()
                code = code.strip()
                if label and code:
                    configured[label] = code
        return configured or DEFAULT_EVDS_SERIES

    def fetch_snapshot(self, series: dict[str, str] | None = None) -> dict:
        if not self.enabled:
            return {
                "key": "tcmb_macro",
                "enabled": False,
                "status": "disabled",
                "fetched": 0,
                "inserted": 0,
                "dedup_skipped": 0,
                "rejected_entity": 0,
                "blocked": 0,
                "retries": 0,
                "last_success_at": None,
                "error": "tcmb_evds_api_key_missing",
                "snapshot": [],
            }

        series_map = self._series_map(series)
        series_expr = ",".join(series_map.values())
        api_key = self.settings.tcmb_evds_api_key.strip()
        params = {"type": "json", "last": 1}
        headers = {"key": api_key}
        try:
            response = httpx.get(
                f"{self.base_url}{series_expr}",
                params=params,
                headers=headers,
                timeout=self.timeout,
            )
            response.raise_for_status()
            payload = response.json()
            items = payload.get("items") or payload.get("series") or []
            latest = items[0] if items else {}
            snapshot = []
            for label, code in series_map.items():
                value = latest.get(code)
                if value in (None, ""):
                    continue
                snapshot.append(
                    {
                        "label": label,
                        "series": code,
                        "value": value,
                        "date": self._normalize_date(latest.get("Tarih") or latest.get("DATE")),
                    }
                )
            now_iso = datetime.now(UTC).isoformat()
            return {
                "key": "tcmb_macro",
                "enabled": True,
                "status": "ok",
                "fetched": len(snapshot),
                "inserted": 0,
                "dedup_skipped": 0,
                "rejected_entity": 0,
                "blocked": 0,
                "retries": 0,
                "last_success_at": now_iso if snapshot else None,
                "error": "",
                "snapshot": snapshot,
            }
        except Exception as exc:  # noqa: BLE001
            try:
                fallback_params = {"type": "json", "last": 1, "key": api_key}
                response = httpx.get(
                    f"{self.base_url}{series_expr}",
                    params=fallback_params,
                    timeout=self.timeout,
                )
                response.raise_for_status()
                payload = response.json()
                items = payload.get("items") or payload.get("series") or []
                latest = items[0] if items else {}
                snapshot = []
                for label, code in series_map.items():
                    value = latest.get(code)
                    if value in (None, ""):
                        continue
                    snapshot.append(
                        {
                            "label": label,
                            "series": code,
                            "value": value,
                            "date": self._normalize_date(latest.get("Tarih") or latest.get("DATE")),
                        }
                    )
                now_iso = datetime.now(UTC).isoformat()
                return {
                    "key": "tcmb_macro",
                    "enabled": True,
                    "status": "ok",
                    "fetched": len(snapshot),
                    "inserted": 0,
                    "dedup_skipped": 0,
                    "rejected_entity": 0,
                    "blocked": 0,
                    "retries": 1,
                    "last_success_at": now_iso if snapshot else None,
                    "error": "",
                    "snapshot": snapshot,
                }
            except Exception:
                return {
                    "key": "tcmb_macro",
                    "enabled": True,
                    "status": "error",
                    "fetched": 0,
                    "inserted": 0,
                    "dedup_skipped": 0,
                    "rejected_entity": 0,
                    "blocked": 0,
                    "retries": 1,
                    "last_success_at": None,
                    "error": str(exc),
                    "snapshot": [],
                }
