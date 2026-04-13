"""Simple alert/notification system for significant BIST events.

Alerts are stored in-memory with optional webhook dispatch. The API
exposes endpoints for listing, acknowledging, and configuring alerts.
"""

from __future__ import annotations

import logging
import threading
import uuid
from datetime import UTC, datetime
from enum import Enum
from typing import Any

import requests

logger = logging.getLogger(__name__)


class AlertSeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class AlertType(str, Enum):
    KAP_MATERIAL_EVENT = "kap_material_event"
    CONTRADICTION_DETECTED = "contradiction_detected"
    HIGH_TENSION = "high_tension"
    PRICE_SPIKE = "price_spike"
    INGEST_FAILURE = "ingest_failure"
    PROVIDER_FAILURE = "provider_failure"
    CACHE_OVERFLOW = "cache_overflow"


class Alert:
    def __init__(
        self,
        alert_type: AlertType,
        severity: AlertSeverity,
        ticker: str,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.alert_id = str(uuid.uuid4())[:12]
        self.alert_type = alert_type
        self.severity = severity
        self.ticker = ticker.upper()
        self.message = message
        self.details = details or {}
        self.created_at = datetime.now(UTC)
        self.acknowledged = False
        self.acknowledged_at: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "alert_id": self.alert_id,
            "alert_type": self.alert_type.value,
            "severity": self.severity.value,
            "ticker": self.ticker,
            "message": self.message,
            "details": self.details,
            "created_at": self.created_at.isoformat(),
            "acknowledged": self.acknowledged,
            "acknowledged_at": self.acknowledged_at.isoformat() if self.acknowledged_at else None,
        }


class AlertManager:
    def __init__(self, max_alerts: int = 500, webhook_url: str = "", webhook_type: str = "slack") -> None:
        self._alerts: list[Alert] = []
        self._lock = threading.Lock()
        self._max = max_alerts
        self._webhook_url = webhook_url.strip()
        self._webhook_type = (webhook_type or "slack").strip().lower()
        self._rules: list[dict[str, Any]] = self._default_rules()

    @staticmethod
    def _default_rules() -> list[dict[str, Any]]:
        return [
            {
                "name": "material_event",
                "alert_type": AlertType.KAP_MATERIAL_EVENT.value,
                "severity": AlertSeverity.WARNING.value,
                "enabled": True,
            },
            {
                "name": "contradiction",
                "alert_type": AlertType.CONTRADICTION_DETECTED.value,
                "severity": AlertSeverity.WARNING.value,
                "enabled": True,
            },
            {
                "name": "high_tension",
                "alert_type": AlertType.HIGH_TENSION.value,
                "severity": AlertSeverity.CRITICAL.value,
                "enabled": True,
                "threshold": 0.7,
            },
            {
                "name": "ingest_failure",
                "alert_type": AlertType.INGEST_FAILURE.value,
                "severity": AlertSeverity.CRITICAL.value,
                "enabled": True,
            },
        ]

    def emit(
        self,
        alert_type: AlertType,
        ticker: str,
        message: str,
        severity: AlertSeverity = AlertSeverity.INFO,
        details: dict[str, Any] | None = None,
    ) -> Alert | None:
        # Check if alert type is enabled
        rule = next((r for r in self._rules if r["alert_type"] == alert_type.value), None)
        if rule and not rule.get("enabled", True):
            return None

        alert = Alert(alert_type=alert_type, severity=severity, ticker=ticker, message=message, details=details)
        with self._lock:
            self._alerts.append(alert)
            if len(self._alerts) > self._max:
                self._alerts = self._alerts[-self._max:]

        logger.info("Alert [%s] %s: %s - %s", alert.severity.value, alert.alert_type.value, ticker, message)
        if alert.severity == AlertSeverity.CRITICAL:
            self._dispatch_webhook(alert)
        return alert

    def _dispatch_webhook(self, alert: Alert) -> None:
        if not self._webhook_url:
            return

        def _send() -> None:
            try:
                requests.post(self._webhook_url, json=self._webhook_payload(alert), timeout=5)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Alert webhook dispatch failed: %s", exc)

        threading.Thread(target=_send, daemon=True).start()

    def _webhook_payload(self, alert: Alert) -> dict[str, Any]:
        text = f"[{alert.severity.value.upper()}] {alert.alert_type.value} {alert.ticker}: {alert.message}"
        if self._webhook_type == "discord":
            return {
                "content": text,
                "embeds": [
                    {
                        "title": f"{alert.ticker} {alert.alert_type.value}",
                        "description": alert.message,
                        "color": 15158332,
                        "timestamp": alert.created_at.isoformat(),
                    }
                ],
            }
        return {"text": text, "blocks": [{"type": "section", "text": {"type": "mrkdwn", "text": text}}]}

    def list_alerts(
        self,
        ticker: str | None = None,
        severity: str | None = None,
        unacknowledged_only: bool = False,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        with self._lock:
            filtered = list(reversed(self._alerts))
        if ticker:
            filtered = [a for a in filtered if a.ticker == ticker.upper()]
        if severity:
            filtered = [a for a in filtered if a.severity.value == severity]
        if unacknowledged_only:
            filtered = [a for a in filtered if not a.acknowledged]
        return [a.to_dict() for a in filtered[:limit]]

    def acknowledge(self, alert_id: str) -> bool:
        with self._lock:
            for alert in self._alerts:
                if alert.alert_id == alert_id:
                    alert.acknowledged = True
                    alert.acknowledged_at = datetime.now(UTC)
                    return True
        return False

    def acknowledge_all(self, ticker: str | None = None) -> int:
        count = 0
        with self._lock:
            for alert in self._alerts:
                if alert.acknowledged:
                    continue
                if ticker and alert.ticker != ticker.upper():
                    continue
                alert.acknowledged = True
                alert.acknowledged_at = datetime.now(UTC)
                count += 1
        return count

    def get_rules(self) -> list[dict[str, Any]]:
        return [dict(r) for r in self._rules]

    def update_rule(self, name: str, enabled: bool | None = None, threshold: float | None = None) -> bool:
        for rule in self._rules:
            if rule["name"] == name:
                if enabled is not None:
                    rule["enabled"] = enabled
                if threshold is not None:
                    rule["threshold"] = threshold
                return True
        return False

    def stats(self) -> dict[str, Any]:
        with self._lock:
            total = len(self._alerts)
            unacked = sum(1 for a in self._alerts if not a.acknowledged)
            by_severity = {}
            for a in self._alerts:
                by_severity[a.severity.value] = by_severity.get(a.severity.value, 0) + 1
        return {
            "total": total,
            "unacknowledged": unacked,
            "by_severity": by_severity,
        }
