from dataclasses import replace

from helpers import NOW
from optplat import committee as cmt
from optplat import decider as d1
from optplat.agents import OPPOSE, SUPPORT, Verdict
from test_committee import CONTRACT, ctx


def v(agent, stance, conf=0.8, role="analyst", **kw):
    return Verdict(agent, role, stance, conf, (f"{agent} says {stance}",), kw.pop("evidence", {}), **kw)


def committee(verdicts, disposition=cmt.REJECT, reasons=("x",), qty=0, net=0.0):
    return cmt.CommitteeDecision(disposition, qty, net, 0.0, tuple(reasons), tuple(verdicts))


def test_strong_agreement_enters_and_sizes_near_the_cap_with_a_thesis_and_an_invalidation():
    vs = [v("technical", SUPPORT, 0.9, evidence={"sma20": 150.0}), v("volatility", SUPPORT, 0.9), v("sentiment", SUPPORT, 0.9), v("flow", SUPPORT, 0.9)]
    out = d1.decide(ctx(cap=10), committee(vs))
    assert out.disposition == cmt.ENTER and out.conviction > 0.85 and out.quantity >= 8
    assert len(out.thesis) == 2 and out.invalidation == {"underlying_closes_through": 150.0, "direction": "below"}


def test_it_can_enter_where_the_committee_net_score_said_no_and_size_scales_with_conviction():
    mixed = [v("technical", SUPPORT, 0.95), v("volatility", SUPPORT, 0.8), v("sentiment", OPPOSE, 0.2), v("flow", SUPPORT, 0.5)]
    out = d1.decide(ctx(cap=10), committee(mixed))
    assert out.disposition == cmt.ENTER and 1 <= out.quantity < 9
    weak = [v("technical", SUPPORT, 0.6), v("volatility", OPPOSE, 0.6), v("sentiment", SUPPORT, 0.3), v("flow", OPPOSE, 0.3)]
    assert d1.decide(ctx(cap=10), committee(weak)).disposition == cmt.REJECT   # below the 0.45 gate: skipped, not sized small


def test_opposition_counts_and_unknown_means_no_trade():
    against = [v("technical", SUPPORT, 0.9), v("volatility", OPPOSE, 0.9), v("sentiment", OPPOSE, 0.9), v("flow", SUPPORT, 0.5)]
    assert d1.decide(ctx(), committee(against)).disposition == cmt.REJECT
    assert d1.decide(ctx(), committee([])).disposition == cmt.REJECT


def test_safety_gates_still_stand_and_the_size_never_exceeds_the_cap():
    vs = [v("technical", SUPPORT, 0.9), v("volatility", SUPPORT, 0.9)]
    gate = v("execution", SUPPORT, 1.0, role="gate", hard_veto=True)
    assert d1.decide(ctx(), committee(vs + [gate])).disposition == cmt.REJECT
    assert d1.decide(ctx(), committee(vs, reasons=("sentiment vetoed: thin",))).disposition == cmt.REJECT
    assert d1.decide(ctx(cap=3), committee(vs)).quantity <= 3
    assert d1.decide(ctx(cap=0), committee(vs)).disposition == cmt.REJECT


def test_engine_journals_the_decider_beside_the_committee_without_touching_orders():
    from test_engine import build
    engine, manager, broker, provider, _ = build(auto_entries=True, committee_mode="shadow")
    engine.run_cycle()
    kinds = {x["kind"] for x in manager.store.list_decisions(limit=200)}
    assert {"COMMITTEE", "DECIDER"} <= kinds
    row = next(x for x in manager.store.list_decisions(kind="DECIDER", limit=10))
    assert "committee_quantity" in row["payload"] and "conviction" in row["payload"]


def test_compare_is_descriptive_with_few_candidates_and_pending_ones_are_not_counted():
    from optplat.store import Store
    out = d1.compare(Store(":memory:"), NOW, True)
    assert out["candidates"] == 0 and out["descriptive_only"] is True and out["committee_dollar_change"] == 0.0
