import pytest

from helpers import make_intent, make_quote
from optplat.broker import SimBroker
from optplat.models import Side
from optplat.orders import (
    MIN_TRADES_FOR_DESCRIPTION,
    OrderManager,
    REPORT_ORDER_LIMIT,
    _wilson_95,
    evidence_summary,
)
from optplat.pricing import sell_limit_for
from optplat.store import Store


def trade(pnl, contract="SPY   260116C00500000"):
    return {"pnl": pnl, "contract": contract}


def test_wilson_interval_is_wide_for_tiny_samples_and_tightens_with_n():
    lo, hi = _wilson_95(1, 1)
    assert lo < 25 and hi == 100.0  # one win proves almost nothing
    lo2, hi2 = _wilson_95(60, 100)
    assert (hi2 - lo2) < (hi - lo)
    assert 0 <= lo2 <= 60 <= hi2 <= 100


def test_empty_report_is_insufficient_and_has_no_interval():
    ev = evidence_summary([])
    assert ev["status"] == "INSUFFICIENT_SAMPLE"
    assert ev["win_rate_95ci_pct"] is None and ev["realized_pnl_without_best_trade"] is None


def test_few_trades_are_flagged_as_anecdotes():
    ev = evidence_summary([trade(100.0)] * 5)
    assert ev["status"] == "INSUFFICIENT_SAMPLE"
    assert any("anecdotes" in n for n in ev["notes"])


def test_enough_trades_is_descriptive_only_never_an_edge():
    ev = evidence_summary([trade(10.0, f"SP{i % 4}   260116C00500000") for i in range(MIN_TRADES_FOR_DESCRIPTION)])
    assert ev["status"] == "DESCRIPTIVE_ONLY"
    assert ev["distinct_underlyings"] == 4
    assert "EDGE" not in ev["status"].upper()


def test_profit_that_rests_on_one_trade_is_called_out():
    ev = evidence_summary([trade(500.0), trade(-100.0), trade(-150.0)])
    assert ev["realized_pnl_without_best_trade"] == -250.0
    assert any("single best trade" in n for n in ev["notes"])


def test_single_underlying_is_called_out():
    assert any("one underlying" in n for n in evidence_summary([trade(1.0), trade(2.0)])["notes"])


def test_truncation_is_reported_not_silent():
    ev = evidence_summary([trade(1.0)], truncated=True)
    assert ev["report_truncated"] is True
    assert any("NOT included" in n for n in ev["notes"])


class _Clock:
    def __call__(self):
        from helpers import NOW
        return NOW


def test_report_exposes_evidence_and_keeps_existing_fields():
    broker = SimBroker()
    broker.set_quote(make_quote())
    manager = OrderManager(broker, Store(":memory:"), clock=_Clock())
    manager.submit(make_intent())
    broker.set_quote(make_quote(2.90, 3.00))
    manager.submit(make_intent("sell-00000001", qty=4, limit=sell_limit_for(2.90), side=Side.SELL_TO_CLOSE))
    report = manager.report()
    assert report["closed_trades"] == 1 and report["win_rate_pct"] == 100.0  # unchanged
    ev = report["evidence"]
    assert ev["status"] == "INSUFFICIENT_SAMPLE" and ev["closed_trades"] == 1
    assert ev["report_truncated"] is False and ev["distinct_underlyings"] == 1


def test_report_limit_constant_is_sane():
    assert REPORT_ORDER_LIMIT >= 1000
