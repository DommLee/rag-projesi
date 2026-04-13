from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path


def main() -> None:
    db_path = Path("data/analyst_workspace.db")
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """
        SELECT event_id, prev_hash, record_hash, event_type, ticker, asset_scope,
               source_key, payload_sha256, session_id, actor, retention_tier, created_at
        FROM audit_ledger
        ORDER BY created_at ASC, rowid ASC
        """
    ).fetchall()
    print(f"count={len(rows)}")
    prev = "GENESIS"
    for index, row in enumerate(rows):
        material = "|".join(
            [
                prev,
                row["event_type"],
                row["ticker"],
                row["asset_scope"],
                row["source_key"],
                row["payload_sha256"],
                row["session_id"],
                row["actor"],
                row["retention_tier"],
                row["created_at"],
            ]
        )
        expected = hashlib.sha256(material.encode("utf-8")).hexdigest()
        if row["prev_hash"] != prev or row["record_hash"] != expected:
            print(
                json.dumps(
                    {
                        "position": index,
                        "expected_prev_hash": prev,
                        "actual_prev_hash": row["prev_hash"],
                        "expected_hash": expected,
                        "actual_hash": row["record_hash"],
                        "row": dict(row),
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return
        prev = row["record_hash"]
    print("ok")


if __name__ == "__main__":
    main()
