from datetime import datetime, timedelta, timezone

from optplat.oos import EVALUATED, INSUFFICIENT, best_of_k_null_prob, oos_report

T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)


def mk(n, pnl=1.0):
    return [{"closed_at": T0 + timedelta(days=i), "pnl": pnl} for i in range(n)]


def test_small_sample_withholds_test_window():
    r = oos_report(mk(59))
    assert r["status"] == INSUFFICIENT and r["test_window"] is None
    assert "edge" in r["note"]


def test_enough_trades_evaluates_latest_slice():
    trades = mk(70, pnl=-1.0)
    for t in trades[-21:]:
        t["pnl"] = 5.0
    r = oos_report(trades)
    assert r["status"] == EVALUATED
    assert r["test_window"]["trades"] == 21 and r["test_window"]["total_pnl"] == 105.0
    assert r["selection_window"]["trades"] == 49 and r["selection_window"]["total_pnl"] == -49.0


def test_split_is_chronological_not_input_order():
    trades = mk(60)
    r1 = oos_report(trades)
    r2 = oos_report(list(reversed(trades)))
    assert r1 == r2


def test_bad_rows_counted_not_dropped_silently():
    rows = mk(10) + [{"closed_at": None, "pnl": 1}, {"closed_at": T0, "pnl": float("nan")},
                     {"closed_at": T0, "pnl": True}, {"closed_at": T0}]
    r = oos_report(rows)
    assert r["excluded"] == 4
    assert r["selection_window"]["trades"] + 3 == 10


def test_small_test_window_blocks_even_with_many_trades():
    r = oos_report(mk(100), test_fraction=0.1)  # 10 < MIN_TEST
    assert r["status"] == INSUFFICIENT


def test_empty_input():
    r = oos_report([])
    assert r["status"] == INSUFFICIENT and r["selection_window"]["mean_pnl"] is None


def test_best_of_k_grows_with_lanes():
    one = best_of_k_null_prob(8, 10, 1)
    many = best_of_k_null_prob(8, 10, 20)
    assert abs(one - 0.0547) < 1e-3
    assert many > 0.6 > one


def test_best_of_k_invalid_inputs():
    assert best_of_k_null_prob(5, 0, 3) is None
    assert best_of_k_null_prob(11, 10, 3) is None
    assert best_of_k_null_prob(5, 10, 0) is None
    assert best_of_k_null_prob(5, 10, 3, p=1.0) is None
