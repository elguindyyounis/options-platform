import sqlite3
from datetime import timedelta

import pytest

from helpers import NOW
from optplat.evaluate import main as evaluate_cli
from optplat.evaluation import evaluate, format_report
from optplat.marketdata import snapshot_to_dict
from optplat.risk import RiskPolicy
from optplat.store import Store
from test_replay import row

ENTRIES = {"auto_entries": True, "reentry_cooldown_s": 0}
STEP = timedelta(seconds=1000)  # one order-ttl bucket apart, so each step may place a fresh order


def alternating_rows(n_steps, fictional=False, up_bid=7.5, up_ask=7.7):
    """Even steps: cheap quote (entry). Odd steps: quote 50% higher (take-profit exit)."""
    out = []
    for i in range(n_steps):
        at = NOW + STEP * i
        bid, ask = (4.90, 5.10) if i % 2 == 0 else (up_bid, up_ask)
        out.append(row(at=at, bid=bid, ask=ask, fictional=fictional, rid=i + 1))
    return out


def test_few_trades_are_reported_as_insufficient_data_not_as_a_result():
    result = evaluate(alternating_rows(8), config=ENTRIES)
    assert result["status"] == "INSUFFICIENT_DATA"
    assert any("closed trades in total" in r for r in result["reasons"])
    assert "descriptive only" in format_report(result)


def test_enough_trades_are_measured_but_never_called_an_edge():
    result = evaluate(alternating_rows(12), config=ENTRIES, min_trades=2, min_oos_trades=1)
    assert result["status"] == "MEASURED" and result["reasons"] == []
    text = format_report(result).lower()
    assert "edge" in text and "not proof of an edge" in text and "no commissions" in text
    assert "has an edge" not in text and "profitable strategy" not in text


def test_the_split_is_chronological_and_each_segment_is_replayed_on_its_own_data():
    result = evaluate(alternating_rows(12), config=ENTRIES, min_trades=2, min_oos_trades=1)
    early, late = result["segments"]
    assert early["name"] == "in_sample" and late["name"] == "out_of_sample"
    assert early["to"] < late["from"]  # no overlap, no peeking across the boundary
    assert early["steps"] + late["steps"] == 12 and late["steps"] >= 2
    assert early["closed_trades"] >= 1 and early["realized_pnl"] > 0  # +50% quote moves are take-profits


def test_out_of_sample_threshold_alone_can_block_a_measured_status():
    result = evaluate(alternating_rows(12), config=ENTRIES, min_trades=2, min_oos_trades=50)
    assert result["status"] == "INSUFFICIENT_DATA"
    assert any("out of sample" in r for r in result["reasons"])


def test_fictional_data_is_always_labelled_meaningless():
    result = evaluate(alternating_rows(12, fictional=True), config=ENTRIES, min_trades=1, min_oos_trades=1)
    assert result["status"] == "FICTIONAL_DATA"
    assert "fictional" in result["reasons"][0].lower()


def test_no_entries_means_no_trades_and_do_nothing_is_the_baseline():
    result = evaluate(alternating_rows(8))
    assert all(s["closed_trades"] == 0 and s["return_pct"] == 0 for s in result["segments"])
    assert result["do_nothing"] == {"return_pct": 0.0, "max_drawdown_pct": 0.0, "closed_trades": 0}


def test_drawdown_is_measured_from_the_equity_peak():
    # entry at the ask, then the quote collapses: the position is marked at the bid and equity falls
    rows = [row(at=NOW + STEP * i, bid=b, ask=a, rid=i + 1)
            for i, (b, a) in enumerate([(4.9, 5.1), (4.9, 5.1), (3.9, 4.1), (3.5, 3.7), (3.4, 3.6), (3.4, 3.6)])]
    result = evaluate(rows, config=ENTRIES, min_trades=1, min_oos_trades=0)
    assert max(s["max_drawdown_pct"] for s in result["segments"]) > 0


def test_underlying_buy_and_hold_is_reported_for_context_per_symbol():
    result = evaluate(alternating_rows(8))
    assert result["underlying_buy_and_hold_pct"] == {"AAA": 0.0}  # the helper snapshots all have the same spot


def test_the_strict_quote_policy_applies_unless_explicitly_relaxed():
    rows = [row(at=NOW + STEP * i, verified=False, bid=(4.9 if i % 2 == 0 else 7.5),
                ask=(5.1 if i % 2 == 0 else 7.7), rid=i + 1) for i in range(8)]
    strict = evaluate(rows, config=ENTRIES, min_trades=1, min_oos_trades=0)
    relaxed = evaluate(rows, config=ENTRIES, min_trades=1, min_oos_trades=0,
                       policy=RiskPolicy(require_verified_quote_time=False))
    assert sum(s["closed_trades"] for s in strict["segments"]) == 0
    assert sum(s["closed_trades"] for s in relaxed["segments"]) >= 1


def test_bad_inputs_are_errors():
    with pytest.raises(ValueError, match="No recorded"):
        evaluate([])
    with pytest.raises(ValueError, match="at least 4"):
        evaluate(alternating_rows(3))
    with pytest.raises(ValueError, match="oos_fraction"):
        evaluate(alternating_rows(8), oos_fraction=0.9)


# ------------------------------------------------------------ read-only store and CLI
def seed_db(path, rows):
    store = Store(str(path))
    from datetime import datetime

    for r in rows:
        store.record_snapshot(r["symbol"], datetime.fromisoformat(r["recorded_at"]),
                              datetime.fromisoformat(r["payload"]["as_of"]), "test", r["fictional"],
                              r["payload"]["timestamp_verified"], r["payload"])


def test_read_only_store_reads_but_cannot_write(tmp_path):
    db = tmp_path / "rec.db"
    seed_db(db, alternating_rows(4))
    ro = Store(str(db), read_only=True)
    assert len(ro.list_snapshots()) == 4
    with pytest.raises(sqlite3.OperationalError):
        ro.set_state("x", "y")


def test_cli_reports_without_modifying_the_database(tmp_path, capsys):
    db = tmp_path / "rec.db"
    seed_db(db, alternating_rows(12))
    before = db.read_bytes()
    code = evaluate_cli(["--db", str(db), "--entries"])
    out = capsys.readouterr().out
    assert code == 0 and "STATUS: INSUFFICIENT_DATA" in out and "Caveats" in out
    assert db.read_bytes() == before


def test_cli_explains_when_entries_are_off_and_when_there_is_no_data(tmp_path, capsys):
    db = tmp_path / "rec.db"
    seed_db(db, alternating_rows(8))
    assert evaluate_cli(["--db", str(db)]) == 0
    assert "--entries" in capsys.readouterr().out
    empty = tmp_path / "empty.db"
    Store(str(empty))
    assert evaluate_cli(["--db", str(empty)]) == 1
    assert "No recorded snapshots" in capsys.readouterr().out
    assert evaluate_cli(["--db", str(tmp_path / "missing.db")]) == 1


def test_cli_leaves_fictional_data_out_unless_asked(tmp_path, capsys):
    db = tmp_path / "rec.db"
    seed_db(db, alternating_rows(8, fictional=True))
    assert evaluate_cli(["--db", str(db), "--entries"]) == 1  # nothing real recorded
    assert evaluate_cli(["--db", str(db), "--entries", "--fictional"]) == 0
    assert "FICTIONAL_DATA" in capsys.readouterr().out
