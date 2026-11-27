"""Main-account orders on IBKR data use the service's per-contract cross-check (synthetic fixtures only)."""
from datetime import timedelta

import pytest

from helpers import CONTRACT, NOW
from optplat.broker import SimBroker
from optplat.engine import TradingEngine
from optplat.ibkr_data import VERIFIED_SOURCE, IBKRDataProvider
from optplat.marketdata import ChainRow, MarketSnapshot, StaticDataProvider
from optplat.models import OptionContract, Right
from optplat.orders import OrderManager
from optplat.risk import RiskPolicy, evaluate
from optplat.store import Store
from optplat.strategy import LiquidTrendStrategy
from helpers import make_intent
from optplat.models import Account


def verified_row(**over):
    row = {'symbol': CONTRACT.underlying, 'expiry': CONTRACT.expiry.isoformat(), 'right': CONTRACT.right.value,
           'strike': CONTRACT.strike, 'multiplier': 100, 'bid': 1.9, 'ask': 2.0, 'market_data_type': 1,
           'status': 'PAPER_VERIFIED', 'execution_eligible': True,
           'source_quote_at': (NOW - timedelta(seconds=1)).isoformat(),
           'received_at': (NOW - timedelta(seconds=0.5)).isoformat()}
    row.update(over)
    return row


def provider_for(row):
    calls = []

    def transport(resource, params=None, **_kw):
        calls.append(resource)
        if isinstance(row, Exception):
            raise row
        return row
    return IBKRDataProvider(transport, clock=lambda: NOW), calls


def test_a_matching_cross_check_is_a_verified_quote_dated_at_the_ibkr_event():
    p, calls = provider_for(verified_row())
    q = p.execution_quote(CONTRACT)
    assert q.timestamp_verified and q.source == VERIFIED_SOURCE and q.as_of == NOW - timedelta(seconds=1)
    assert calls == ['execution-quote']
    # It satisfies the risk policy's verified-time rule that every unverified IBKR quote fails.
    assert evaluate(make_intent(limit=2.02), q, Account(100_000, 100_000, 0), [], RiskPolicy(), now=NOW).allowed


@pytest.mark.parametrize('over', [
    {'status': 'LIVE_UNVERIFIED'}, {'execution_eligible': False}, {'market_data_type': 3},
    {'source_quote_at': (NOW - timedelta(seconds=6)).isoformat()},
    {'received_at': (NOW - timedelta(seconds=9)).isoformat()},
    {'source_quote_at': (NOW + timedelta(seconds=3)).isoformat()},
    {'source_quote_at': '2026-11-16T15:00:00'},           # no timezone
    {'strike': CONTRACT.strike + 1}, {'right': 'P'}, {'symbol': 'QQQ'},
    {'bid': 2.1}, {'ask': 0.0}, {'bid': float('nan')},
])
def test_any_doubt_means_no_verified_quote(over):
    assert provider_for(verified_row(**over))[0].execution_quote(CONTRACT) is None


def test_service_refusal_means_no_verified_quote():
    assert provider_for(RuntimeError('503 PAPER_QUOTE_VERIFICATION_UNAVAILABLE'))[0].execution_quote(CONTRACT) is None


def test_decision_quotes_are_live_but_never_verified():
    rows = {'rows': [verified_row(status='LIVE_UNVERIFIED', execution_eligible=False),
                     verified_row(strike=999.0, status='LIVE_UNVERIFIED')]}
    p, _ = provider_for(rows)
    other = OptionContract(CONTRACT.underlying, CONTRACT.expiry, Right.PUT, CONTRACT.strike)
    out = p.decision_quotes_for([CONTRACT, other])
    assert [q.contract for q in out] == [CONTRACT]
    assert out[0].timestamp_verified is False and out[0].source == 'ibkr'
    assert not evaluate(make_intent(limit=2.02), out[0], Account(100_000, 100_000, 0), [], RiskPolicy(), now=NOW).allowed
    stale = {'rows': [verified_row(status='STALE')]}
    assert provider_for(stale)[0].decision_quotes_for([CONTRACT]) == []


def test_lanes_still_get_no_ibkr_quotes():
    assert provider_for(verified_row())[0].quotes_for([CONTRACT]) == []


# ------------------------------------------------------------------ engine
EXPIRY = NOW.date() + timedelta(days=60)
UP = tuple(100.0 + i for i in range(60))
C = OptionContract("AAA", EXPIRY, Right.CALL, 160.0)


class IBKRLikeProvider(StaticDataProvider):
    """Unverified IBKR-style snapshots, plus a scripted cross-check."""

    def __init__(self, clock, verified):
        super().__init__(clock)
        self.verified = verified  # callable(contract) -> Quote | None
        self.asked = []

    def execution_quote(self, contract):
        self.asked.append(contract)
        return self.verified(contract)


def ibkr_snapshot(bid, ask):
    return MarketSnapshot("AAA", UP[-1], UP, (ChainRow(C, bid, ask, 200, 2000, 0.3),), NOW, "ibkr-shared-research-only", False)


def build(verified):
    from optplat.models import Quote

    class Clock:
        now = NOW

        def __call__(self):
            return self.now
    clock = Clock()
    provider = IBKRLikeProvider(clock, verified)
    provider.set_snapshot(ibkr_snapshot(4.90, 5.10))
    broker = SimBroker()
    manager = OrderManager(broker, Store(":memory:"), clock=clock)
    engine = TradingEngine(manager, provider, LiquidTrendStrategy(), clock=clock)
    engine.set_config({"watchlist": ["AAA"], "auto_entries": True})
    return engine, broker, provider, Quote


def test_entry_fills_only_on_a_verified_quote():
    engine, broker, provider, Quote = build(lambda c: Quote(c, 4.90, 5.10, NOW, VERIFIED_SOURCE, timestamp_verified=True))
    report = engine.run_cycle()
    assert report["entries"][0]["result"] == "FILLED" and len(broker.get_positions()) == 1
    assert report["quote_verifications"][0]["result"] == "VERIFIED" and provider.asked == [C]


def test_entry_without_verification_is_refused_by_the_risk_policy():
    engine, broker, provider, _ = build(lambda c: None)
    report = engine.run_cycle()
    entry = report["entries"][0]
    assert entry["result"] == "RISK_REJECTED" and broker.get_positions() == []
    assert any("not verified" in f for f in entry["risk_failures"])
    assert report["quote_verifications"][0]["result"] == "NOT_VERIFIED"


def test_exit_uses_the_verified_bid():
    state = {"bid": 4.90, "ask": 5.10}
    engine, broker, provider, Quote = build(
        lambda c: Quote(c, state["bid"], state["ask"], NOW, VERIFIED_SOURCE, timestamp_verified=True))
    engine.run_cycle()
    state.update(bid=3.0, ask=3.2)
    provider.set_snapshot(ibkr_snapshot(3.0, 3.2))
    item = engine.run_cycle()["exits"][0]
    assert (item["trigger"], item["result"]) == ("stop_loss", "FILLED") and broker.get_positions() == []


def test_verifications_are_capped_per_cycle():
    engine, _, provider, _ = build(lambda c: None)
    engine._verifications_left = 0
    engine._verification_log = []
    assert engine._verified_quote(C) is None and provider.asked == []
    assert engine._verification_log == [{"contract": C.occ_symbol.strip(), "result": "BUDGET_SPENT_THIS_CYCLE"}]
    report = engine.run_cycle()  # a new cycle restores the budget
    assert report["quote_verifications"][0]["result"] == "NOT_VERIFIED"
    assert TradingEngine.MAX_QUOTE_VERIFICATIONS_PER_CYCLE == 3


# ---- owner-triggered pipeline test (2026-11-27)
def test_pipeline_test_buys_then_sells_one_contract_on_verified_quotes():
    from optplat.models import Side
    engine, broker, provider, Quote = build(lambda c: Quote(c, 4.90, 5.10, NOW, VERIFIED_SOURCE, timestamp_verified=True))
    buy = engine.pipeline_test_order(C, Side.BUY_TO_OPEN)
    assert buy["result"] == "FILLED" and buy["order"]["intent"]["quantity"] == 1
    assert buy["order"]["intent"]["limit_price"] == 5.15 and len(broker.get_positions()) == 1
    sell = engine.pipeline_test_order(C, Side.SELL_TO_CLOSE)
    assert sell["result"] == "FILLED" and sell["order"]["intent"]["limit_price"] == 4.86 and broker.get_positions() == []


def test_pipeline_test_never_trades_without_verification_or_past_the_kill_switch():
    from optplat.models import Side
    engine, broker, _, _ = build(lambda c: None)
    assert engine.pipeline_test_order(C, Side.BUY_TO_OPEN)["result"] == "NOT_VERIFIED" and broker.get_positions() == []
    engine2, broker2, _, Quote = build(lambda c: Quote(c, 4.90, 5.10, NOW, VERIFIED_SOURCE, timestamp_verified=True))
    engine2.manager.set_kill_switch(True, "test")
    assert engine2.pipeline_test_order(C, Side.BUY_TO_OPEN)["result"] == "RISK_REJECTED" and broker2.get_positions() == []


def test_pipeline_test_needs_a_verifying_provider():
    from optplat.models import Side
    engine, _, _, _ = build(lambda c: None)
    engine.provider = StaticDataProvider(engine.clock)
    assert engine.pipeline_test_order(C, Side.BUY_TO_OPEN)["result"] == "UNAVAILABLE"


def test_owner_test_settings_for_the_main_account():
    from optplat import __main__ as entry
    assert (entry.MAIN_MAX_SPREAD_PCT, entry.MAIN_MIN_DTE, entry.MAIN_MAX_DTE) == (25.0, 21, 200)
    assert RiskPolicy().max_spread_pct_of_ask == 15.0 and LiquidTrendStrategy().max_spread_pct == 10.0  # defaults kept
