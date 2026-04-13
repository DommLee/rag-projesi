from __future__ import annotations

import gzip
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


class RawDocumentLake:
    """Compressed append-only-ish raw payload storage.

    The audit ledger stores event hashes; this layer keeps the payload bytes in
    gzip-compressed JSON files so connector evidence can be inspected later
    without bloating SQLite.
    """

    def __init__(self, root_dir: str = "data/raw_docs") -> None:
        self.root = Path(root_dir)
        self.root.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _safe_part(value: str) -> str:
        safe = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in str(value or "unknown"))
        return safe.strip("_")[:80] or "unknown"

    @staticmethod
    def _json_bytes(payload: Any) -> bytes:
        return json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")

    def write_json(
        self,
        *,
        category: str,
        source_key: str,
        ticker: str = "",
        payload: Any,
        retention_tier: str = "permanent",
    ) -> dict:
        canonical = {
            "category": category,
            "source_key": source_key,
            "ticker": ticker.upper() if ticker else "",
            "retention_tier": retention_tier,
            "payload": payload,
        }
        sha = hashlib.sha256(self._json_bytes(canonical)).hexdigest()
        raw = self._json_bytes({**canonical, "stored_at": datetime.now(UTC).isoformat()})
        date_part = datetime.now(UTC).strftime("%Y%m%d")
        path = (
            self.root
            / self._safe_part(category)
            / self._safe_part(source_key)
            / self._safe_part(ticker.upper() if ticker else "global")
            / date_part
            / f"{sha}.json.gz"
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        existed = path.exists()
        if not existed:
            with gzip.open(path, "wb", compresslevel=9) as handle:
                handle.write(raw)
        compressed_bytes = path.stat().st_size if path.exists() else 0
        return {
            "retained_path": str(path),
            "payload_sha256": sha,
            "raw_bytes": len(raw),
            "compressed_bytes": compressed_bytes,
            "compression_ratio": round(compressed_bytes / max(1, len(raw)), 4),
            "dedup_existing": existed,
            "retention_tier": retention_tier,
        }

    def summary(self) -> dict:
        files = list(self.root.rglob("*.json.gz")) if self.root.exists() else []
        compressed_bytes = sum(path.stat().st_size for path in files if path.exists())
        categories = {}
        for path in files:
            try:
                category = path.relative_to(self.root).parts[0]
            except Exception:  # noqa: BLE001
                category = "unknown"
            categories[category] = categories.get(category, 0) + 1
        return {
            "root": str(self.root),
            "file_count": len(files),
            "compressed_bytes": compressed_bytes,
            "compressed_mb": round(compressed_bytes / (1024 * 1024), 4),
            "categories": categories,
            "storage_mode": "gzip_json_hash_dedup",
        }
