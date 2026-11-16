import json
from datetime import datetime, timedelta, timezone

import pytest

import optplat.research as research
from helpers import NOW
from optplat.marketdata import snapshot_to_dict
from optplat.research import (BASELINE, BASELINE_FINGERPRINT, StrategySpec, baseline_is_frozen, build_strategy,
                              evaluate_hypothesis, fingerprint, main, register, validate_criteria, verify)
from optplat.store import Store

CRIT = {"metric": "expectancy_per_trade", "min_improvement": 5.0}
CHALLENGER = {"name": "liquid-trend", "version": "0.2.0-test", "params": {"min_volume": 80}}
REG = datetime(2026, 11, 16, 14, 0, tzinfo=timezone.utc)


def store_with_rows(rows):
    store = Store(":memory:")
    for r in rows:
        store.record_snapshot(r["symbol"], datetime.fromisoformat(r["recorded_at"]),
                              datetime.fromisoformat(r["payload"]["as_of"]), "test", r["fictional"],
                              r["payload"]["timestamp_verified"], r["payload"])
    return store


def market_rows(days=4):
    """Inside the NYSE session, 1000 s apart. Each even step one fresh contract (a new expiry/strike pair) quotes
    tight and cheap and every other contract quotes wide, so only it is proposed; the next step it quotes 50%
    higher (a take-profit). That gives the baseline about 11 distinct trades a day, clear of the 24 h cooldown."""
    from dataclasses import replace

    from optplat.marketdata import ChainRow
    from optplat.models import OptionContract, Right
    from test_engine import EXPIRY, snapshot

    out, rid = [], 1
    for d in range(days):
        t0 = datetime(2026, 11, 16 + d, 14, 35, tzinfo=timezone.utc)
        expiry = EXPIRY + timedelta(days=7 * d)
        for k in range(22):
            active = 152.0 + k // 2
            rows = []
            for strike in range(152, 163):
                c = OptionContract("AAA", expiry, Right.CALL, float(strike))
                if float(strike) == active:
                    bid, ask = (4.90, 5.10) if k % 2 == 0 else (7.5, 7.7)
                else:
                    bid, ask = 1.0, 2.0  # 67% spread: never proposed
                rows.append(ChainRow(c, bid, ask, 200, 2000, 0.3))
            at = t0 + timedelta(seconds=1000 * k)
            snap = replace(snapshot(), rows=tuple(rows), as_of=at)
            out.append({"id": rid, "symbol": "AAA", "recorded_at": at.isoformat(), "fictional": False,
                        "payload": snapshot_to_dict(snap)})
            rid += 1
    return out


# ------------------------------------------------------------ frozen baseline
def test_the_baseline_is_frozen_by_fingerprint():
    assert baseline_is_frozen() and fingerprint(BASELINE) == BASELINE_FINGERPRINT
    assert fingerprint(StrategySpec("liquid-trend", "0.1.0", (("min_dte", 31),))) != BASELINE_FINGERPRINT


def test_a_moved_baseline_blocks_registration_and_evaluation(monkeypatch):
    store = Store(":memory:")
    hid = register(store, "x", CHALLENGER, CRIT, REG)
    monkeypatch.setattr(research, "BASELINE_FINGERPRINT", "moved")
    with pytest.raises(RuntimeError, match="baseline"):
        register(store, "y", CHALLENGER, CRIT, REG)
    with pytest.raises(RuntimeError, match="baseline"):
        evaluate_hypothesis(store, hid)


def test_build_strategy_applies_parameters_and_version():
    s = build_strategy(StrategySpec.from_dict(CHALLENGER))
    assert s.min_volume == 80 and s.version == "0.2.0-test" and build_strategy(BASELINE).min_volume == 50


# ------------------------------------------------------------ registration rules
def test_registration_validates_everything_it_stores():
    store = Store(":memory:")
    with pytest.raises(ValueError, match="statement"):
        register(store, "  ", CHALLENGER, CRIT)
    with pytest.raises(ValueError, match="Unknown strategy"):
        register(store, "x", {"name": "magic", "version": "1"}, CRIT)
    with pytest.raises(ValueError, match="Unknown parameter"):
        register(store, "x", {**CHALLENGER, "params": {"take_profit_pct": 99}}, CRIT)  # exits/risk are not strategy params
    with pytest.raises(ValueError, match="must be a number"):
        register(store, "x", {**CHALLENGER, "params": {"min_dte": "30"}}, CRIT)
    with pytest.raises(ValueError, match="identically"):
        register(store, "x", {"name": "liquid-trend", "version": "relabelled", "params": {}}, CRIT)
    assert store.list_hypotheses() == []


def test_criteria_cannot_be_laxer_than_the_evaluation_minimums_or_empty_promises():
    for bad in ({"min_improvement": 5, "min_trades": 29}, {"min_improvement": 5, "min_oos_trades": 9},
                {"min_improvement": 0}, {}, {"min_improvement": 5, "metric": "vibes"},
                {"min_improvement": 5, "max_drawdown_worsening_pct": 6}):
        with pytest.raises(ValueError):
            validate_criteria(bad)
    ok = validate_criteria({"min_improvement": 5, "min_trades": 100})
    assert ok["min_trades"] == 100 and ok["min_oos_trades"] == 10 and ok["metric"] == "expectancy_per_trade"


def test_hypotheses_get_sequential_ids_and_a_verifiable_hash():
    store = Store(":memory:")
    a = register(store, "first", CHALLENGER, CRIT, REG)
    b = register(store, "second", {**CHALLENGER, "params": {"min_volume": 90}}, CRIT, REG)
    assert (a, b) == ("H-0001", "H-0002")
    assert all(verify(h) for h in store.list_hypotheses())


def test_hypotheses_are_append_only_and_tampering_is_detected():
    store = Store(":memory:")
    hid = register(store, "first", CHALLENGER, CRIT, REG)
    assert not any(hasattr(store, n) for n in ("update_hypothesis", "delete_hypothesis"))
    with store._lock:  # someone edits the stored criteria directly in the database
        raw = json.loads(store._db.execute("SELECT payload FROM hypotheses").fetchone()[0])
        raw["criteria"]["min_improvement"] = 0.001
        store._db.execute("UPDATE hypotheses SET payload=?", (json.dumps(raw, sort_keys=True),))
        store._db.commit()
    assert not verify(store.get_hypothesis(hid))
    with pytest.raises(RuntimeError, match="altered"):
        evaluate_hypothesis(store, hid)


# ------------------------------------------------------------ evaluation rules
def test_confirmatory_uses_only_snapshots_recorded_after_registration():
    rows = market_rows(days=4)
    store = store_with_rows(rows)
    hid = register(store, "x", CHALLENGER, CRIT, datetime(2026, 11, 18, 0, 0, tzinfo=timezone.utc))  # after days 0 and 1
    seen_before = len([r for r in rows if datetime.fromisoformat(r["recorded_at"]) <= datetime(2026, 11, 18, tzinfo=timezone.utc)])
    result = evaluate_hypothesis(store, hid, now=NOW + timedelta(days=9))
    assert result["snapshots_used"] == len(rows) - seen_before and seen_before > 0
    exploratory = evaluate_hypothesis(store, hid, mode="exploratory", now=NOW + timedelta(days=9))
    assert exploratory["snapshots_used"] == len(rows)


def test_exploratory_runs_can_never_pass():
    store = store_with_rows(market_rows(days=4))
    hid = register(store, "x", CHALLENGER, CRIT, REG - timedelta(days=30))
    out = evaluate_hypothesis(store, hid, mode="exploratory")
    assert out["status"] in ("EXPLORATORY_ONLY", "INSUFFICIENT_DATA") and out["status"] != "PASSED_CRITERIA"


def test_too_little_data_is_insufficient_not_a_verdict():
    store = store_with_rows(market_rows(days=1))
    hid = register(store, "x", CHALLENGER, CRIT, REG)
    out = evaluate_hypothesis(store, hid)
    assert out["status"] == "INSUFFICIENT_DATA" and out["reasons"]
    empty = Store(":memory:")
    hid2 = register(empty, "x", CHALLENGER, CRIT, REG)
    assert evaluate_hypothesis(empty, hid2)["status"] == "INSUFFICIENT_DATA"


def test_a_challenger_that_does_not_beat_the_baseline_fails_its_pre_registered_bar_and_the_verdict_is_final(monkeypatch):
    store = store_with_rows(market_rows(days=4))
    hid = register(store, "wider volume filter", CHALLENGER, CRIT, REG)  # behaves the same on this data
    first = evaluate_hypothesis(store, hid, now=NOW + timedelta(days=10))
    assert first["status"] == "FAILED_CRITERIA", first["reasons"]
    assert first["challenger"]["out_of_sample"]["closed_trades"] >= 10
    monkeypatch.setattr(research, "evaluate", lambda *a, **k: (_ for _ in ()).throw(AssertionError("recomputed")))
    again = evaluate_hypothesis(store, hid)  # no second look: the recorded verdict is returned
    assert again["status"] == "FAILED_CRITERIA" and again["already_final"] is True
    assert len([r for r in store.hypothesis_results(hid) if r["status"] == "FAILED_CRITERIA"]) == 1


def fake_eval(c_is, c_oos, b_is, b_oos):
    def seg(name, closed, exp, dd=0.0):
        return {"name": name, "closed_trades": closed, "expectancy_per_trade": exp, "realized_pnl": (exp or 0) * closed,
                "return_pct": (exp or 0) * closed / 1000, "max_drawdown_pct": dd}
    calls = iter([[seg("in_sample", 25, c_is[0], c_is[1]), seg("out_of_sample", 15, c_oos[0], c_oos[1])],
                  [seg("in_sample", 25, b_is[0], b_is[1]), seg("out_of_sample", 15, b_oos[0], b_oos[1])]])
    return lambda *a, **k: {"segments": next(calls)}


@pytest.mark.parametrize("c_is,c_oos,b_is,b_oos,status", [
    ((12, 1), (20, 1), (10, 1), (10, 1), "PASSED_CRITERIA"),
    ((12, 1), (14, 1), (10, 1), (10, 1), "FAILED_CRITERIA"),   # improves by 4 < required 5
    ((8, 1), (20, 1), (10, 1), (10, 1), "FAILED_CRITERIA"),    # better out of sample but worse in sample: inconsistent
    ((12, 1), (20, 4), (10, 1), (10, 1), "FAILED_CRITERIA"),   # deeper drawdown than allowed
    ((12, 1), (20, 1.5), (10, 1), (10, 1), "PASSED_CRITERIA"), # drawdown within the 2-point allowance
])
def test_verdict_logic(monkeypatch, c_is, c_oos, b_is, b_oos, status):
    store = Store(":memory:")
    hid = register(store, "x", CHALLENGER, {**CRIT, "max_drawdown_worsening_pct": 2.0}, REG)
    monkeypatch.setattr(research, "evaluate", fake_eval(c_is, c_oos, b_is, b_oos))
    monkeypatch.setattr(research.Store, "list_snapshots", lambda self, **k: [], raising=False)
    assert evaluate_hypothesis(store, hid, now=NOW)["status"] == status


def test_too_few_trades_in_either_arm_is_insufficient_even_if_the_numbers_look_great(monkeypatch):
    store = Store(":memory:")
    hid = register(store, "x", CHALLENGER, CRIT, REG)

    def seg(closed_oos):
        return [{"closed_trades": 20, "expectancy_per_trade": 50.0, "realized_pnl": 1.0, "return_pct": 1.0, "max_drawdown_pct": 0.0},
                {"closed_trades": closed_oos, "expectancy_per_trade": 50.0, "realized_pnl": 1.0, "return_pct": 1.0, "max_drawdown_pct": 0.0}]
    arms = iter([{"segments": seg(15)}, {"segments": seg(3)}])
    monkeypatch.setattr(research, "evaluate", lambda *a, **k: next(arms))
    out = evaluate_hypothesis(store, hid)
    assert out["status"] == "INSUFFICIENT_DATA" and any("out of sample" in r for r in out["reasons"])


def test_results_always_carry_the_multiple_testing_count_and_never_claim_an_edge():
    store = store_with_rows(market_rows(days=4))
    register(store, "a", {**CHALLENGER, "params": {"min_volume": 70}}, CRIT, REG)
    hid = register(store, "b", CHALLENGER, CRIT, REG)
    out = evaluate_hypothesis(store, hid)
    assert out["hypotheses_registered"] == 2
    text = json.dumps(out["caveats"]).lower()
    assert "not proof of an edge" in text and "more hypotheses" in text and "owner's decision" in text


# ------------------------------------------------------------ CLI
def test_cli_registers_lists_and_evaluates(tmp_path, capsys):
    db = str(tmp_path / "r.db")
    assert main(["--db", db, "register", "--statement", "tighter volume", "--challenger", json.dumps(CHALLENGER),
                 "--criteria", json.dumps(CRIT)]) == 0
    assert "Registered H-0001" in capsys.readouterr().out
    assert main(["--db", db, "list"]) == 0
    listing = capsys.readouterr().out
    assert "H-0001" in listing and "NOT_EVALUATED" in listing
    assert main(["--db", db, "evaluate", "H-0001"]) == 0
    assert "INSUFFICIENT_DATA" in capsys.readouterr().out
    assert main(["--db", db, "register", "--statement", "x", "--challenger", "{not json", "--criteria", "{}"]) == 1
    assert main(["--db", db, "evaluate", "H-9999"]) == 1
