from dataclasses import replace
from datetime import timedelta

import pytest

from helpers import NOW
from optplat import committee as cmt
from datetime import date

from optplat.agents import ABSTAIN, OPPOSE, SUPPORT, Context, events, execution, exposure, run_agent, skeptic, technical, volatility
from optplat.events import Event, EventCalendar, EventView, FOMC_DECISION_DAYS, yahoo_earnings_dates
from optplat.marketdata import ChainRow, snapshot_to_dict
from optplat.models import Account, OptionContract, Position, Right
from optplat.risk import RiskPolicy
from optplat.store import Store
from optplat.strategy import Proposal
from test_engine import EXPIRY, UP, build, snapshot

CONTRACT = OptionContract("AAA", EXPIRY, Right.CALL, 160.0)
ACCOUNT = Account(equity=100_000.0, cash=100_000.0, open_premium=0.0)


def calm(**row_kw):
    """An uptrend with realistic day-to-day noise and a fairly priced, deep-open-interest option."""
    closes = tuple(c + (0.8 if i % 2 else -0.8) for i, c in enumerate(UP))
    snap = snapshot()
    row = replace(snap.rows[0], iv=0.12, volume=1000, open_interest=100_000, **row_kw)
    return replace(snap, closes=closes, underlying=closes[-1], rows=(row,))


QUIET = EventView(macro=(), earnings=(), is_etf=False)  # a stock with confirmed nothing scheduled


def ctx(snap=None, *, contract=CONTRACT, cap=10, positions=(), now=NOW, limit=5.10, account=ACCOUNT, ev=QUIET):
    snap = snap or calm()
    return Context(snap, Proposal(contract, limit, 90.0, {}), now, account, RiskPolicy(), tuple(positions), cap, events=ev)


def with_row(snap, **kw):
    row = replace(snap.rows[0], **kw)
    return replace(snap, rows=(row,))


# ------------------------------------------------------------ agents
def test_technical_supports_a_call_in_an_uptrend_and_opposes_a_put():
    v = technical(ctx())
    assert v.stance == SUPPORT
    assert any("chasing" in r for r in v.reasons) and v.confidence < 0.5  # a steep, overbought run is marked down
    put = OptionContract("AAA", EXPIRY, Right.PUT, 160.0)
    snap = replace(calm(), rows=(ChainRow(put, 4.9, 5.1, 200, 100_000, 0.12),))
    assert technical(ctx(snap, contract=put)).stance == OPPOSE


def test_technical_abstains_without_enough_history():
    snap = replace(calm(), closes=UP[:30])
    assert technical(ctx(snap)).stance == ABSTAIN


def test_volatility_flags_rich_premium_and_abstains_without_iv():
    assert volatility(ctx(with_row(calm(), iv=None))).stance == ABSTAIN
    rich = volatility(ctx(with_row(calm(), iv=3.0)))
    assert rich.stance == OPPOSE and rich.evidence["iv_to_rv"] > 1.5


def test_execution_hard_vetoes_a_wide_spread_and_a_missing_quote():
    assert execution(ctx(with_row(calm(), bid=3.0, ask=5.1))).hard_veto
    other = OptionContract("AAA", EXPIRY, Right.CALL, 999.0)
    assert execution(ctx(contract=other)).hard_veto  # no row for it: unknown means no


def test_exposure_vetoes_stacking_the_same_bet():
    held = [Position(OptionContract("AAA", EXPIRY, Right.CALL, 150.0), 1, 6.0)]
    v = exposure(ctx(positions=held))
    assert v.veto and not v.hard_veto


def test_skeptic_always_lists_objections_and_vetoes_only_on_blocking_ones():
    v = skeptic(ctx())
    assert v.evidence["objections"] and any(o["severity"] == "minor" for o in v.evidence["objections"])
    assert not v.veto
    stale = skeptic(ctx(now=NOW + timedelta(hours=2)))
    assert stale.veto and stale.stance == OPPOSE


def test_a_crashing_agent_fails_closed():
    def boom(_ctx):
        raise RuntimeError("x")

    boom.__name__ = "execution"
    assert run_agent(boom, ctx()).hard_veto


# ------------------------------------------------------------ committee bounds
def test_committee_never_uses_more_than_the_cap_and_is_never_below_one_when_it_enters():
    for cap in (1, 2, 7, 100):
        for trust in (0.2, 0.5, 1.0):
            d = cmt.decide(ctx(cap=cap), {}, trust)
            if d.disposition == cmt.ENTER:
                assert 1 <= d.quantity <= cap
            else:
                assert d.quantity == 0


def test_size_grows_with_trust_and_stays_within_the_cap():
    low = cmt.decide(ctx(cap=40), {}, 0.5)
    high = cmt.decide(ctx(cap=40), {}, 1.0)
    assert low.disposition == high.disposition == cmt.ENTER
    assert low.quantity < high.quantity <= 40


def test_hard_veto_always_rejects_whatever_the_weights_say():
    d = cmt.decide(ctx(with_row(calm(), bid=3.0, ask=5.1)), {"execution": 2.0, "technical": 2.0}, 1.0)
    assert d.disposition == cmt.REJECT and d.quantity == 0


def test_a_learnable_veto_stops_counting_once_the_agent_has_lost_trust():
    held = [Position(OptionContract("AAA", EXPIRY, Right.CALL, 150.0), 1, 6.0)]
    assert cmt.decide(ctx(positions=held), {}, 1.0).disposition == cmt.REJECT
    assert cmt.decide(ctx(positions=held), {"exposure": 0.3}, 1.0).disposition == cmt.ENTER


def test_a_candidate_against_the_trend_is_rejected():
    put = OptionContract("AAA", EXPIRY, Right.PUT, 160.0)
    snap = replace(calm(), rows=(ChainRow(put, 4.9, 5.1, 200, 100_000, 0.12),))
    assert cmt.decide(ctx(snap, contract=put), {}, 1.0).disposition == cmt.REJECT


# ------------------------------------------------------------ learning
def seed(store, hits, *, agent="technical", stance=SUPPORT, disposition=cmt.ENTER, fictional=False, start=0):
    """One decision per entry in `hits`; the contract bid 4h later is up for True and down for False."""
    for i, up in enumerate(hits, start=start):
        at = NOW + timedelta(hours=10 * i)
        contract = OptionContract("AAA", EXPIRY, Right.CALL, 160.0 + i)
        ref = 5.0
        store.record_decision(at, "AAA", cmt.KIND, disposition, contract.occ_symbol.strip(), "t:1", ref, None, fictional,
                              {"contract": contract.to_dict(),
                               "verdicts": [{"agent": agent, "stance": stance, "confidence": 0.8}]})
        later = at + timedelta(hours=4)
        row = ChainRow(contract, 6.0 if up else 4.0, 6.2 if up else 4.2, 100, 1000, 0.3)
        snap = replace(snapshot(), rows=(row,), as_of=later)
        store.record_snapshot("AAA", later, later, "t", fictional, True, snapshot_to_dict(snap))


def test_an_agent_that_keeps_being_right_gains_weight_and_one_that_is_wrong_loses_it():
    now = NOW + timedelta(days=30)
    right, wrong = Store(":memory:"), Store(":memory:")
    seed(right, [True] * 40)
    seed(wrong, [False] * 40)
    w_right = cmt.fit(right, now, False)["technical"]
    w_wrong = cmt.fit(wrong, now, False)["technical"]
    assert w_right["weight"] > 1.0 > w_wrong["weight"]
    assert cmt.WEIGHT_MIN <= w_wrong["weight"] and w_right["weight"] <= cmt.WEIGHT_MAX


def test_a_short_record_moves_the_weight_only_a_little():
    store = Store(":memory:")
    seed(store, [False] * 3)
    assert cmt.fit(store, NOW + timedelta(days=5), False)["technical"]["weight"] > 0.85


def test_the_experimental_agent_starts_small_and_can_earn_influence():
    assert cmt.start_weight("sentiment") < cmt.start_weight("technical")
    store = Store(":memory:")
    seed(store, [True] * 60, agent="sentiment")
    assert cmt.fit(store, NOW + timedelta(days=40), False)["sentiment"]["weight"] > 0.8


def test_trust_starts_at_half_rises_with_wins_and_falls_with_losses():
    now = NOW + timedelta(days=30)
    assert cmt.fit(Store(":memory:"), now, False)["committee"]["weight"] == cmt.TRUST_START
    win, lose = Store(":memory:"), Store(":memory:")
    seed(win, [True] * 60)
    seed(lose, [False] * 60)
    assert cmt.fit(win, now, False)["committee"]["weight"] > 0.5 > cmt.fit(lose, now, False)["committee"]["weight"]


def test_learn_writes_an_audit_row_and_current_reads_it_back():
    store, now = Store(":memory:"), NOW + timedelta(days=30)
    seed(store, [False] * 40)
    cmt.learn(store, now, False)
    rows = store.list_agent_weights(False)
    assert any(r["agent"] == "technical" and "to" in r["note"] for r in rows)
    weights, trust = cmt.current(store, False)
    assert weights["technical"] < 1.0 and trust < cmt.TRUST_START
    before = len(store.list_agent_weights(False))
    cmt.learn(store, now, False)  # nothing new: no new rows
    assert len(store.list_agent_weights(False)) == before


def test_learning_keeps_fictional_and_real_apart():
    store, now = Store(":memory:"), NOW + timedelta(days=30)
    seed(store, [False] * 40, fictional=True)
    assert cmt.fit(store, now, False)["technical"]["n"] == 0
    assert cmt.fit(store, now, True)["technical"]["n"] == 40


def test_lessons_name_who_was_wrong_and_who_was_right():
    store, now = Store(":memory:"), NOW + timedelta(days=30)
    seed(store, [False], agent="technical")
    out = cmt.scorecard(store, now, False)
    assert out["lessons"] and "Entered and lost" in out["lessons"][0] and "Wrong: technical" in out["lessons"][0]


# ------------------------------------------------------------ engine wiring
def test_shadow_mode_changes_no_order_and_records_the_committee_vote():
    engine_off, m_off, *_ = build(auto_entries=True, committee_mode="off")
    engine_sh, m_sh, *_ = build(auto_entries=True, committee_mode="shadow")
    engine_off.run_cycle()
    engine_sh.run_cycle()
    key = lambda m: [(o.intent.contract, o.intent.quantity, o.state) for o in m.list()]  # noqa: E731
    assert key(m_off) == key(m_sh)
    assert any(d["kind"] == cmt.KIND for d in m_sh.store.list_decisions())
    assert not any(d["kind"] == cmt.KIND for d in m_off.store.list_decisions())


def test_active_mode_takes_no_more_than_the_baseline_and_journals_the_vote():
    engine_b, m_b, *_ = build(auto_entries=True, committee_mode="off")
    engine_a, m_a, *_ = build(auto_entries=True, committee_mode="active")
    engine_b.run_cycle()
    engine_a.run_cycle()
    base = [o.intent.quantity for o in m_b.list()]
    act = [o.intent.quantity for o in m_a.list()]
    assert len(act) <= len(base) and all(a <= b for a, b in zip(act, base))
    assert any(d["kind"] == cmt.KIND for d in m_a.store.list_decisions())


def test_active_mode_with_a_crashing_committee_places_nothing(monkeypatch):
    engine, manager, *_ = build(auto_entries=True, committee_mode="active")
    monkeypatch.setattr(cmt, "decide", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    report = engine.run_cycle()
    assert manager.list() == [] and any(e.get("result") == "COMMITTEE_DECLINED" for e in report["entries"])


def test_committee_mode_is_validated_and_defaults_to_shadow():
    engine, *_ = build()
    assert engine.config().committee_mode == "shadow"
    with pytest.raises(ValueError, match="committee_mode"):
        engine.set_config({"committee_mode": "live"})


# ------------------------------------------------------------ API and launcher
def test_committee_endpoint_requires_the_token_and_reports_mode_weights_and_lessons():
    from fastapi.testclient import TestClient

    from optplat.api import create_app
    from optplat.broker import SimBroker
    from optplat.engine import EngineConfig, TradingEngine
    from optplat.marketdata import DemoDataProvider
    from optplat.orders import OrderManager
    from optplat.strategy import LiquidTrendStrategy

    manager = OrderManager(SimBroker(), Store(":memory:"))
    engine = TradingEngine(manager, DemoDataProvider(), LiquidTrendStrategy(), default_config=EngineConfig())
    tok = "t" * 24
    with TestClient(create_app(manager, tok, engine)) as c:
        assert c.get("/api/committee").status_code == 401
        body = c.get("/api/committee", headers={"X-API-Token": tok}).json()
        assert body["mode"] == "shadow" and body["trust"] == cmt.TRUST_START and "skeptic" in body["weights"]
        assert body["fictional"] is True and body["lessons"] == []
        ok = c.put("/api/engine/config", json={"committee_mode": "active"}, headers={"X-API-Token": tok})
        assert ok.status_code == 200 and ok.json()["committee_mode"] == "active"
        assert c.put("/api/engine/config", json={"committee_mode": "live"}, headers={"X-API-Token": tok}).status_code == 422


def test_quantity_never_exceeds_the_cap_under_extreme_weights_and_trust():
    import itertools

    agents_ = ("technical", "volatility", "sentiment", "execution", "exposure", "skeptic")
    for cap, w, trust in itertools.product((1, 3, 50), (cmt.WEIGHT_MIN, 1.0, cmt.WEIGHT_MAX), (cmt.TRUST_MIN, 0.5, 1.0)):
        d = cmt.decide(ctx(cap=cap), {a: w for a in agents_}, trust)
        assert d.quantity <= cap and d.scale <= 1.0


# ------------------------------------------------------------ events
def E(kind, d, tentative=False):
    return Event(kind, d, "test", tentative)


def test_unknown_earnings_for_a_single_stock_is_a_hard_veto_but_not_for_an_etf():
    unknown = events(ctx(ev=EventView(macro=(), earnings=None, is_etf=False)))
    assert unknown.hard_veto and "unknown" in unknown.reasons[0]
    assert not events(ctx(ev=EventView(macro=(), earnings=(), is_etf=True))).hard_veto
    assert events(ctx(ev=None)).hard_veto  # no calendar consulted at all: fail closed


def test_earnings_within_five_days_is_a_learnable_veto_and_later_earnings_only_weigh():
    near = events(ctx(ev=EventView((), (E("EARNINGS", NOW.date() + timedelta(days=3)),), False)))
    assert near.veto and not near.hard_veto and near.stance == OPPOSE
    far = events(ctx(ev=EventView((), (E("EARNINGS", NOW.date() + timedelta(days=40)),), False)))
    assert not far.veto and far.stance == OPPOSE and far.confidence < 0.5


def test_an_fomc_decision_tomorrow_opposes_but_one_next_month_does_not():
    soon = events(ctx(ev=EventView((E("FOMC", NOW.date() + timedelta(days=1), True),), (), True)))
    assert soon.stance == OPPOSE and "tentative" in soon.reasons[0]
    assert events(ctx(ev=EventView((E("FOMC", NOW.date() + timedelta(days=20)),), (), True))).stance == ABSTAIN


def test_a_macro_calendar_that_does_not_cover_the_dates_says_so_rather_than_claiming_none():
    cal = EventCalendar()
    assert cal.macro(date(2026, 11, 16), date(2027, 3, 1)) is not None
    assert cal.macro(date(2027, 11, 16), date(2028, 2, 1)) is None


def test_calendar_dates_match_the_fed_table_and_mark_2027_tentative():
    assert date(2026, 12, 9) in FOMC_DECISION_DAYS[2026] and len(FOMC_DECISION_DAYS[2026]) == 8
    got = EventCalendar().macro(date(2027, 1, 1), date(2027, 2, 1))
    assert [(e.day, e.tentative) for e in got] == [(date(2027, 1, 27), True)]


def test_earnings_calendar_etfs_unknown_cache_and_failures():
    calls = []

    def source(sym):
        calls.append(sym)
        return {"AAPL": [date(2026, 12, 1)], "BAD": None}.get(sym)

    cal = EventCalendar(earnings_source=source, clock=lambda: NOW)
    assert cal.earnings("SPY", NOW.date(), NOW.date() + timedelta(days=90)) == []  # funds have no earnings
    assert [e.day for e in cal.earnings("AAPL", NOW.date(), NOW.date() + timedelta(days=90))] == [date(2026, 12, 1)]
    cal.earnings("AAPL", NOW.date(), NOW.date() + timedelta(days=90))
    assert calls.count("AAPL") == 1  # cached
    assert cal.earnings("BAD", NOW.date(), NOW.date() + timedelta(days=90)) is None
    assert EventCalendar().earnings("AAPL", NOW.date(), NOW.date()) is None  # no source: unknown

    def boom(sym):
        raise RuntimeError("down")

    assert EventCalendar(earnings_source=boom).earnings("AAPL", NOW.date(), NOW.date()) is None


def test_yahoo_earnings_parsing_empty_and_failure_with_a_fake_library(monkeypatch):
    import sys
    import types
    from datetime import datetime as dt

    answers = {"GOOD": {"Earnings Date": [date(2026, 12, 3), dt(2027, 1, 5, 12, 0)]}, "EMPTY": {}, "NONE": None}

    class FakeTicker:
        def __init__(self, sym):
            if sym == "BOOM":
                raise RuntimeError("network")
            self.calendar = answers[sym]

    monkeypatch.setitem(sys.modules, "yfinance", types.SimpleNamespace(Ticker=FakeTicker))
    assert yahoo_earnings_dates("GOOD") == [date(2026, 12, 3), date(2027, 1, 5)]
    assert yahoo_earnings_dates("EMPTY") is None and yahoo_earnings_dates("NONE") is None  # cannot tell "none" from "unpublished"
    assert yahoo_earnings_dates("BOOM") is None


def test_the_skeptic_flags_a_missing_calendar():
    v = skeptic(ctx(ev=None))
    assert any("no event calendar" in o["text"] for o in v.evidence["objections"])


def test_the_committee_rejects_a_single_stock_with_unknown_earnings_whatever_the_weights():
    d = cmt.decide(ctx(ev=EventView((), None, False)), {"events": 0.25, "technical": 2.0}, 1.0)
    assert d.disposition == cmt.REJECT and any("events" in r for r in d.reasons)


def test_engine_passes_its_calendar_and_unknown_earnings_decline_the_entry():
    engine, manager, _, provider, _ = build(auto_entries=True, committee_mode="active")
    provider.set_snapshot(calm())
    report = engine.run_cycle()  # default calendar has no earnings source and AAA is not a fund
    assert manager.list() == [] and any(e.get("result") == "COMMITTEE_DECLINED" for e in report["entries"])
    why = [d["payload"].get("why", "") for d in manager.store.list_decisions() if d["disposition"] == "NOT_CHOSEN_COMMITTEE"]
    assert any("events" in w for w in why)


def test_engine_enters_when_the_committee_agrees_and_never_above_the_baseline_quantity():
    base, m_base, _, p_base, _ = build(auto_entries=True, committee_mode="off")
    p_base.set_snapshot(calm())
    base.run_cycle()
    eng, mgr, _, prov, _ = build(auto_entries=True, committee_mode="active")
    prov.set_snapshot(calm())
    eng.calendar = EventCalendar(earnings_source=lambda s: [])
    eng.run_cycle()
    placed, baseline = mgr.list(), m_base.list()
    assert len(placed) == 1 and baseline and placed[0].intent.quantity <= baseline[0].intent.quantity
