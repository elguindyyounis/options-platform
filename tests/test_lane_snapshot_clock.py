"""Lanes judge a chain against the clock when it arrives, not when their check began (2026-11-27 open)."""
from dataclasses import replace
from datetime import timedelta

from optplat import optionlanes as ol
from test_optionlanes import make, opened, uptrend


def slow_lane(delay_s, extra_ahead_s=0.0):
    data, now = uptrend()
    lane, prov, store, box = make(replace(ol.SWING_AGGR, symbols=("AAPL",), budget_usd=20000.0), daily=data, now=now)
    base = prov.snapshot_window

    def slow(symbol, *a, **k):
        box[0] = box[0] + timedelta(seconds=delay_s)          # the read takes this long; the clock moves on
        snap = base(symbol, *a, **k)                          # stamped when it arrives
        return replace(snap, as_of=snap.as_of + timedelta(seconds=extra_ahead_s))
    prov.snapshot_window = slow
    return lane, prov, store


def test_a_slow_chain_read_is_not_mistaken_for_a_future_quote():
    lane, prov, store = slow_lane(30)
    out = lane.step(force=True)
    assert not any("FUTURE_TIMESTAMP" in e for e in out["errors"]), out["errors"]
    assert len(opened(lane, prov, store)) == 1


def test_a_quote_truly_ahead_of_the_clock_is_still_refused():
    lane, prov, store = slow_lane(30, extra_ahead_s=60)
    out = lane.step(force=True)
    assert any("FUTURE_TIMESTAMP" in e for e in out["errors"]) and opened(lane, prov, store) == []
