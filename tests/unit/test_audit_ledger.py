from app.audit.ledger import AnalystAuditLedger


def test_audit_ledger_chain_verifies(tmp_path) -> None:
    ledger = AnalystAuditLedger(str(tmp_path / "analyst_workspace.db"))
    first = ledger.append_event(event_type="ingest", payload={"docs": 2}, ticker="ASELS", source_key="kap")
    second = ledger.append_event(event_type="analysis", payload={"coverage": 0.9}, ticker="ASELS", source_key="analysis_engine")

    assert first["event_id"]
    assert second["event_id"]
    verify = ledger.verify_chain("ASELS")
    assert verify["ok"] is True
    assert verify["count"] == 2
    assert verify["event_type_counts"]["ingest"] == 1
    assert verify["event_type_counts"]["analysis"] == 1
    assert verify["source_key_counts"]["kap"] == 1
    assert verify["first_event_id"] is not None
    assert verify["last_event_id"] is not None


def test_audit_ledger_profile_and_snapshot(tmp_path) -> None:
    ledger = AnalystAuditLedger(str(tmp_path / "analyst_workspace.db"))
    ledger.save_analysis_snapshot("ASELS", "default:1", "summary", {"response": {"ok": True}})
    ledger.save_ticker_profile("ASELS", {"consistency": "aligned", "citation_coverage": 0.8})

    latest = ledger.latest_analysis_snapshot("ASELS")
    profile = ledger.get_ticker_profile("ASELS")

    assert latest is not None
    assert latest["summary"] == "summary"
    assert profile is not None
    assert profile["profile"]["consistency"] == "aligned"


def test_audit_ledger_filtered_verify_uses_global_chain(tmp_path) -> None:
    ledger = AnalystAuditLedger(str(tmp_path / "analyst_workspace.db"))
    ledger.append_event(event_type="ingest", payload={"docs": 2}, ticker="ASELS", source_key="kap")
    ledger.append_event(event_type="ingest", payload={"docs": 1}, ticker="THYAO", source_key="news")
    ledger.append_event(event_type="analysis", payload={"coverage": 0.9}, ticker="ASELS", source_key="analysis_engine")

    verify_all = ledger.verify_chain()
    verify_asels = ledger.verify_chain("ASELS")

    assert verify_all["ok"] is True
    assert verify_all["count"] == 3
    assert verify_asels["ok"] is True
    assert verify_asels["count"] == 2
    assert verify_asels["ticker_breakdown"]["ASELS"] == 2
    assert verify_all["ticker_breakdown"]["THYAO"] == 1


def test_audit_ledger_auto_repairs_legacy_chain(tmp_path) -> None:
    db_path = tmp_path / "analyst_workspace.db"
    ledger = AnalystAuditLedger(str(db_path))
    ledger.append_event(event_type="ingest", payload={"docs": 2}, ticker="ASELS", source_key="kap")
    ledger.append_event(event_type="analysis", payload={"coverage": 0.9}, ticker="ASELS", source_key="analysis_engine")

    with ledger._connect() as conn:  # noqa: SLF001 - intentional test tampering
        conn.execute("UPDATE audit_ledger SET prev_hash='BROKEN' WHERE rowid=2")

    repaired = AnalystAuditLedger(str(db_path))
    verify = repaired.verify_chain("ASELS")
    repairs = repaired.list_repairs()

    assert verify["ok"] is True
    assert verify["repair_count"] >= 1
    assert repairs
    assert repairs[0]["repaired_rows"] >= 1
