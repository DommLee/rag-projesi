from __future__ import annotations

import hashlib
from datetime import UTC, datetime


class ClaimLedger:
    """
    Immutable hash registry for cited claims.
    Used to detect unsupported repeated statements.
    """

    def __init__(self) -> None:
        self._claim_hashes: set[str] = set()
        self._unsupported_hashes: set[str] = set()
        self._events: list[dict] = []

    @staticmethod
    def _hash_claim(claim: str) -> str:
        return hashlib.sha256(claim.strip().lower().encode("utf-8")).hexdigest()

    def register(self, claim: str, supported: bool) -> str:
        claim_hash = self._hash_claim(claim)
        self._claim_hashes.add(claim_hash)
        if not supported:
            self._unsupported_hashes.add(claim_hash)
        self._events.append(
            {
                "claim_hash": claim_hash,
                "supported": supported,
                "ts": datetime.now(UTC).isoformat(),
            }
        )
        return claim_hash

    def is_repeated_unsupported(self, claim: str) -> bool:
        claim_hash = self._hash_claim(claim)
        return claim_hash in self._unsupported_hashes

    def stats(self) -> dict:
        total = len(self._claim_hashes)
        unsupported = len(self._unsupported_hashes)
        return {
            "total_claims": total,
            "unsupported_claims": unsupported,
            "unsupported_ratio": 0.0 if total == 0 else unsupported / total,
        }

