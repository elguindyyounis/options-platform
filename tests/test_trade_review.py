from datetime import datetime, timedelta, timezone

from optplat import trade_review as tr

T0 = datetime(2026, 11, 20, 15, tzinfo=timezone.utc)


def trade(status="CLOSED", entry=2.0, exit_price=2.6, pnl=120.0, pnl_pct=30.0, reason="take_profit", committee=None):
    return {"status": status, "entry_price": entry, "entry_time": T0.isoformat(), "exit_price": exit_price if status == "CLOSED" else None,
            "exit_time": (T0 + timedelta(days=2)).isoformat() if status == "CLOSED" else None, "pnl": pnl, "pnl_pct": pnl_pct,
            "exit_reason": reason, "entry_reason": None, "committee": committee, "contract": "C1"}


def pts(*bids, start_days=0.5):
    return [{"contract": "C1", "ts": (T0 + timedelta(days=start_days + i * 0.5)).isoformat(), "bid": b} for i, b in enumerate(bids)]


def test_exit_that_left_money_on_the_table_is_called_early_with_a_hypothesis_to_test():
    path = tr.index_points(pts(2.4, 2.6) + pts(3.2, 3.4, start_days=2.5))["C1"]
    r = tr.review(trade(), path)
    assert r["verdict"] == "EXITED_EARLY" and r["after_exit"]["best_vs_exit_pct"] > 15 and any("X6" in x for x in r["try_next"])


def test_exit_before_a_fall_looks_right_and_a_flat_path_is_mixed():
    down = tr.review(trade(), tr.index_points(pts(2.5, 2.6) + pts(2.2, 2.0, start_days=2.5))["C1"])
    assert down["verdict"] == "EXIT_LOOKED_RIGHT"
    mixed = tr.review(trade(), tr.index_points(pts(2.5, 2.6) + pts(2.9, 2.55, start_days=2.5))["C1"])
    assert mixed["verdict"] == "EXIT_MIXED"


def test_no_price_after_the_exit_is_unknown_never_guessed_and_every_trade_gets_a_review():
    r = tr.review(trade(), [])
    assert r["verdict"] == "UNKNOWN" and r["after_exit"] is None and r["notes"]
    loss = tr.review(trade(exit_price=1.4, pnl=-120.0, pnl_pct=-30.0, reason="stop_loss"), [])
    assert loss["result"] == "LOSS" and "STOP_LOSS" in loss["tags"] and loss["try_next"]
    op = tr.review(trade(status="OPEN", pnl=None, pnl_pct=None, reason=None), [])
    assert op["verdict"] == "OPEN" and op["notes"]


def test_a_gain_given_back_is_flagged_and_the_committee_entry_is_quoted():
    path = tr.index_points(pts(2.8, 2.9, 2.2))["C1"]  # up 45% during the hold, closed at 30% -> not less than half kept
    kept = tr.review(trade(committee={"net_score": 1.1, "quantity": 3}), path)
    assert "GAVE_BACK" not in kept["tags"] and "net conviction 1.1" in kept["notes"][0]
    gave = tr.review(trade(exit_price=2.1, pnl=20.0, pnl_pct=5.0), path)
    assert "GAVE_BACK" in gave["tags"]


def test_trades_endpoint_carries_a_review_on_every_trade():
    from test_engine import build
    engine, manager, broker, provider, _ = build(auto_entries=True)
    engine.run_cycle()
    from optplat.trades import build_trades
    out = build_trades(manager, 50, True)
    assert out["trades"] and all(t["review"]["notes"] for t in out["trades"])
