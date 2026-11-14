from dataclasses import replace

import pytest

from optplat.agents import ABSTAIN, OPPOSE, SUPPORT, Context, flow
from optplat.committee import decide, start_weight
from optplat.engine import TradingEngine
from test_committee import ctx


def with_flow(c, rows, age_h=2.0):
    return replace(c, flow=None if rows is None else {"as_of": "x", "age_h": age_h, "rows": rows})


def row(right, side, usd=200_000):
    return {"contract": "AAA", "right": right, "likely_side": side, "quoted_turnover_usd": usd, "volume_oi_ratio": 9.0}


def test_with_no_scan_or_no_flow_on_the_name_the_agent_abstains():
    assert flow(ctx()).stance == ABSTAIN
    assert flow(with_flow(ctx(), None)).stance == ABSTAIN
    assert flow(with_flow(ctx(), [])).stance == ABSTAIN


def test_a_stale_scan_or_unclear_or_tiny_flow_is_not_used():
    assert "hours old" in flow(with_flow(ctx(), [row("P", "BUY")], age_h=30)).reasons[0]
    assert flow(with_flow(ctx(), [row("P", "UNCLEAR")])).stance == ABSTAIN
    assert flow(with_flow(ctx(), [row("P", "BUY", 5_000)])).stance == ABSTAIN


def test_bought_puts_oppose_a_call_candidate_and_it_is_experimental_and_low_confidence():
    v = flow(with_flow(ctx(), [row("P", "BUY")]))   # ctx() proposes a call
    assert v.stance == OPPOSE and v.experimental and 0 < v.confidence <= 0.6 and not v.veto and not v.hard_veto
    assert flow(with_flow(ctx(), [row("C", "SELL")])).stance == OPPOSE      # sold calls lean bearish too


def test_flow_that_agrees_never_supports_it_only_records_that_it_would_have():
    v = flow(with_flow(ctx(), [row("C", "BUY")]))
    assert v.stance == ABSTAIN and v.evidence["would_support"] is True and v.evidence["supports_enabled"] is False


def test_mixed_flow_abstains():
    v = flow(with_flow(ctx(), [row("C", "BUY", 120_000), row("P", "BUY", 100_000)]))
    assert v.stance == ABSTAIN and "mixed" in v.reasons[0]


def test_the_agent_can_only_make_the_committee_stricter():
    w = {}
    base = decide(ctx(), w, 0.5)
    against = decide(with_flow(ctx(), [row("P", "BUY")]), w, 0.5)
    agrees = decide(with_flow(ctx(), [row("C", "BUY")]), w, 0.5)
    assert against.net_score < base.net_score
    assert agrees.net_score == base.net_score and agrees.quantity == base.quantity and agrees.disposition == base.disposition
    assert start_weight("flow") == 0.25   # earns influence, does not start with it


def test_the_engine_builds_the_flow_view_from_the_newest_scan():
    from datetime import timedelta
    from helpers import NOW
    from optplat.store import Store
    eng = TradingEngine.__new__(TradingEngine)
    eng.store = Store(":memory:")
    eng.provider = type("P", (), {"fictional": True})()
    assert eng._flow_view("AAA", NOW) is None
    scan = {"as_of": (NOW - timedelta(hours=3)).isoformat(), "unusual": [{"symbol": "AAA", "contract": "c", "right": "P", "likely_side": "BUY", "quoted_turnover_usd": 5, "volume_oi_ratio": 4},
                                                                   {"symbol": "BBB", "contract": "d", "right": "C"}]}
    eng.store.record_scan(NOW, True, scan)
    v = eng._flow_view("AAA", NOW)
    assert v["age_h"] == 3.0 and len(v["rows"]) == 1 and v["rows"][0]["right"] == "P"
