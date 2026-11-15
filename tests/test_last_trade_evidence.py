"""Challenge C8: carry the provider's last-trade time as display-only evidence.

It must never accept, reject, size or re-key anything.
"""
from dataclasses import replace
from datetime import datetime, timedelta, timezone

from helpers import NOW
from test_engine import EXPIRY, build, snapshot

from optplat.marketdata import OLD_TRADE_HOURS, ChainRow, last_trade_evidence, rows_from_records
from optplat.models import OptionContract, Right


class _Stamp:  # stands in for a pandas Timestamp
    def __init__(self, dt):
        self._dt = dt

    def to_pydatetime(self):
        return self._dt


def _row(**kw):
    return ChainRow(OptionContract("AAA", EXPIRY, Right.CALL, 100.0), 1.0, 1.2, 10, 50, None, **kw)


def _records(value):
    rec = {"strike": 100, "bid": 1.0, "ask": 1.2, "lastTradeDate": value}
    return rows_from_records([rec], "AAA", EXPIRY, Right.CALL)[0]


def test_parses_aware_times_to_utc_and_rejects_the_rest():
    aware = datetime(2026, 11, 13, 20, 0, tzinfo=timezone(timedelta(hours=-5)))
    assert _records(_Stamp(aware)).last_trade_at == aware.astimezone(timezone.utc)
    assert _records("2026-11-13T20:00:00Z").last_trade_at == datetime(2026, 11, 13, 20, tzinfo=timezone.utc)
    for bad in (None, "", "garbage", 12345, _Stamp(datetime(2026, 11, 13)), float("nan")):
        assert _records(bad).last_trade_at is None  # naive or unparseable means unknown, never guessed
    assert rows_from_records([{"strike": 100, "bid": 1.0, "ask": 1.2}], "AAA", EXPIRY, Right.CALL)[0].last_trade_at is None


def test_evidence_statuses():
    assert last_trade_evidence(_row(), NOW)["last_trade_status"] == "UNKNOWN"
    recent = last_trade_evidence(_row(last_trade_at=NOW - timedelta(hours=2)), NOW)
    assert recent["last_trade_status"] == "RECENT" and recent["last_trade_age_hours"] == 2.0
    old = last_trade_evidence(_row(last_trade_at=NOW - timedelta(hours=OLD_TRADE_HOURS + 1)), NOW)
    assert old["last_trade_status"] == "OLD"
    future = last_trade_evidence(_row(last_trade_at=NOW + timedelta(hours=1)), NOW)
    assert future["last_trade_status"] == "UNKNOWN" and future["last_trade_age_hours"] is None


def _with_trade(trade):
    snap = snapshot()
    return replace(snap, rows=tuple(replace(r, last_trade_at=trade) for r in snap.rows))


def test_engine_entry_reports_evidence_but_old_trades_still_enter_and_do_not_rekey():
    engine, manager, broker, provider, _ = build(auto_entries=True)
    provider.set_snapshot(_with_trade(NOW - timedelta(days=10)))
    entry = engine.run_cycle()["entries"][0]
    # Display only: an OLD last trade is shown, not used to block (that would be a strategy change).
    assert entry["result"] == "FILLED"
    assert entry["last_trade"]["last_trade_status"] == "OLD"
    assert len(manager.list()) == 1


def test_unknown_last_trade_is_reported_as_unknown_and_order_is_identical():
    a, ma, *_ = build(auto_entries=True)
    b, mb, _, pb, _ = build(auto_entries=True)
    pb.set_snapshot(_with_trade(NOW - timedelta(hours=1)))
    ea, eb = a.run_cycle()["entries"][0], b.run_cycle()["entries"][0]
    assert ea["last_trade"]["last_trade_status"] == "UNKNOWN"
    assert eb["last_trade"]["last_trade_status"] == "RECENT"
    # The order intent (what idempotency compares) is the same with or without the evidence.
    assert ma.list()[0].intent.note == mb.list()[0].intent.note
    assert ma.list()[0].intent.limit_price == mb.list()[0].intent.limit_price
