"""Tests for the SQLite-backed ClaimLedger and MemoryStore.

These guarantee that the persistence layer:
- writes through to disk on register/upsert,
- hydrates correctly on a fresh process (we simulate "restart" by
  closing the first instance and opening a second one against the same
  file),
- still satisfies the original in-memory contract.
"""

from __future__ import annotations

from app.memory.claim_ledger import ClaimLedger
from app.memory.store import MemoryStore


def test_claim_ledger_in_memory_only_still_works() -> None:
    ledger = ClaimLedger()
    ledger.register("THYAO net karı geçen çeyreğe göre arttı.", supported=True)
    ledger.register("EREGL hisse hedef fiyatı 250 TL.", supported=False)
    stats = ledger.stats()
    assert stats["total_claims"] == 2
    assert stats["unsupported_claims"] == 1
    assert ledger.is_repeated_unsupported("EREGL hisse hedef fiyatı 250 TL.")
    assert not ledger.is_repeated_unsupported("THYAO net karı geçen çeyreğe göre arttı.")


def test_claim_ledger_persists_across_restart(tmp_path) -> None:
    db_path = tmp_path / "ledger.db"
    first = ClaimLedger(db_path=db_path)
    first.register("ASELS yeni sözleşme imzaladı.", supported=True)
    first.register("Garanti BBVA temettü ödeyecek.", supported=False)
    first.close()

    # Simulate a process restart by opening a brand new ledger against
    # the same SQLite file. The previously registered claims must come
    # back from disk without any explicit re-registration.
    second = ClaimLedger(db_path=db_path)
    stats = second.stats()
    assert stats["total_claims"] == 2
    assert stats["unsupported_claims"] == 1
    assert stats["persistent_count"] == 2
    assert second.is_repeated_unsupported("Garanti BBVA temettü ödeyecek.")


def test_memory_store_snapshot_persistence(tmp_path) -> None:
    db_path = tmp_path / "memory.db"
    store = MemoryStore(db_path=db_path)
    store.upsert_ticker_snapshot(
        "ASELS",
        week_key="2026-W14",
        summary="Yeni KAP duyurusu ve haber çerçevesi uyumlu.",
        themes=["sozlesme", "uretim", "ihracat"],
    )
    store.upsert_ticker_snapshot(
        "ASELS",
        week_key="2026-W15",
        summary="Yeni haber dalgası ortaya çıktı.",
        themes=["haber", "yatirim"],
    )
    store.close()

    fresh = MemoryStore(db_path=db_path)
    snapshots = fresh.get_ticker_snapshots("ASELS")
    assert "2026-W14" in snapshots
    assert "2026-W15" in snapshots
    assert "uretim" in snapshots["2026-W14"]["themes"]
    stats = fresh.stats()
    assert stats["snapshots_total"] == 2
    assert stats["tickers_with_snapshots"] == 1
