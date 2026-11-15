from optplat.orders import exit_audit_fields
from test_engine import build, snapshot


def test_closed_row_records_trigger_quote_time_and_fill_vs_bid():
    engine, manager, broker, provider, _ = build(auto_entries=True)
    engine.run_cycle()
    provider.set_snapshot(snapshot(bid=3.0, ask=3.2))
    assert engine.run_cycle()["exits"][0]["trigger"] == "stop_loss"
    row = manager.report()["closed"][0]
    assert row["exit_trigger"] == "stop_loss"
    assert row["trigger_bid"] == 3.0
    assert row["exit_quote_at"] is not None
    assert row["fill_vs_trigger_bid"] == round(row["exit"] - 3.0, 4)


def test_exactly_one_trigger_record_per_exit_order():
    engine, manager, _, provider, _ = build(auto_entries=True)
    engine.run_cycle()
    provider.set_snapshot(snapshot(bid=3.0, ask=3.2))
    engine.run_cycle()
    engine.run_cycle()
    kinds = [e["kind"] for e in manager.store.audit_events()]
    assert kinds.count("exit_trigger") == 1


def test_unrecorded_close_is_unknown_not_guessed():
    out = exit_audit_fields(None, 3.0)
    assert out["exit_trigger"] == "UNKNOWN"
    assert out["exit_quote_at"] is None and out["fill_vs_trigger_bid"] is None


def test_missing_bid_gives_no_slippage_number():
    out = exit_audit_fields({"trigger": "take_profit", "quote_as_of": "x"}, 3.0)
    assert out["exit_trigger"] == "take_profit" and out["fill_vs_trigger_bid"] is None
