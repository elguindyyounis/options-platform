import math
from datetime import date, timedelta

from helpers import NOW
from optplat.marketdata import (
    ChainRow,
    DemoDataProvider,
    MarketSnapshot,
    StaticDataProvider,
    bs_price,
    rows_from_records,
)
from optplat.models import OptionContract, Right
from optplat.pricing import buy_limit_for, sell_limit_for
from optplat.strategy import LiquidTrendStrategy

EXPIRY = NOW.date() + timedelta(days=60)


def row(strike=160.0, right=Right.CALL, bid=4.90, ask=5.10, vol=200, oi=2000, expiry=EXPIRY):
    return ChainRow(OptionContract("AAA", expiry, right, strike), bid, ask, vol, oi, 0.3)


def snap(closes, rows, underlying=None):
    return MarketSnapshot("AAA", underlying or closes[-1], tuple(closes), tuple(rows), NOW, "test", True)


UP = [100.0 + i for i in range(60)]
DOWN = [200.0 - i for i in range(60)]
FLAT = [100.0 + (i % 2) for i in range(60)]


# ---------------------------------------------------------------- strategy
def test_uptrend_proposes_calls_only():
    rows = [row(160, Right.CALL), row(160, Right.PUT)]
    proposals = LiquidTrendStrategy().propose(snap(UP, rows), NOW)
    assert [p.contract.right for p in proposals] == [Right.CALL]
    assert proposals[0].rationale["trend"] == "UP"
    assert proposals[0].limit_price == buy_limit_for(5.10)


def test_downtrend_proposes_puts_only():
    rows = [row(140, Right.CALL), row(140, Right.PUT)]
    proposals = LiquidTrendStrategy().propose(snap(DOWN, rows), NOW)
    assert [p.contract.right for p in proposals] == [Right.PUT]


def test_no_clear_trend_or_short_history_means_no_proposals():
    assert LiquidTrendStrategy().propose(snap(FLAT, [row(100)]), NOW) == []
    assert LiquidTrendStrategy().propose(snap(UP[:30], [row(130)]), NOW) == []


def test_filters_drop_illiquid_wide_far_or_mis_dated_contracts():
    rows = [
        row(160, bid=3.0, ask=5.10),                       # spread too wide
        row(160, oi=100),                                  # open interest too low
        row(160, vol=5),                                   # volume too low
        row(200),                                          # too far from the money
        row(160, expiry=NOW.date() + timedelta(days=10)),  # too soon
        row(160, expiry=NOW.date() + timedelta(days=400)), # too far out
        row(160, bid=0.0, ask=0.05),                       # no bid
        row(160, bid=5.20, ask=5.10),                      # crossed
    ]
    assert LiquidTrendStrategy().propose(snap(UP, rows), NOW) == []


def test_best_scoring_contract_comes_first_and_ordering_is_deterministic():
    tight_atm = row(160, bid=4.95, ask=5.05, oi=3000)
    looser = row(165, bid=3.00, ask=3.20, oi=800)
    result = LiquidTrendStrategy().propose(snap(UP, [looser, tight_atm]), NOW)
    assert result[0].contract.strike == 160
    assert result == LiquidTrendStrategy().propose(snap(UP, [tight_atm, looser]), NOW)


# ---------------------------------------------------------------- pricing helpers
def test_buy_limit_stays_within_policy_and_is_fillable_by_the_sim():
    for cents in range(1, 3000):
        ask = cents / 100
        limit = buy_limit_for(ask)
        assert ask - 1e-9 <= limit <= ask * 1.01 + 1e-9, ask
        assert limit >= round(ask * 1.005, 2) - 1e-9, ask  # sim fills at ask + 0.5% slippage


def test_sell_limit_stays_within_policy_and_is_fillable_by_the_sim():
    for cents in range(1, 3000):
        bid = cents / 100
        limit = sell_limit_for(bid)
        assert bid * 0.97 - 1e-9 <= limit <= bid + 1e-9, bid
        assert limit <= round(bid * 0.995, 2) + 1e-9, bid  # sim fills at bid - 0.5% slippage


# ---------------------------------------------------------------- providers
def clock():
    return NOW


def test_demo_provider_is_deterministic_and_internally_consistent():
    a = DemoDataProvider(clock=clock).snapshot("SPY")
    b = DemoDataProvider(clock=clock).snapshot("SPY")
    assert a == b and a.fictional and a.timestamp_verified
    assert a.rows and all(0 < r.bid <= r.ask for r in a.rows)
    assert all(r.contract.expiry >= NOW.date() + timedelta(days=7) for r in a.rows)


def test_demo_provider_advance_moves_prices_and_quotes_follow():
    p = DemoDataProvider(clock=clock)
    first = p.snapshot("SPY")
    p.advance()
    second = p.snapshot("SPY")
    assert second.underlying != first.underlying
    c = second.rows[0].contract
    q = p.quotes_for([c])[0]
    assert q.contract == c and q.timestamp_verified and q.as_of == NOW


def test_demo_market_trends_let_the_baseline_strategy_trade_both_directions():
    p = DemoDataProvider(clock=clock)
    strategy = LiquidTrendStrategy()
    spy = strategy.propose(p.snapshot("SPY"), NOW)
    qqq = strategy.propose(p.snapshot("QQQ"), NOW)
    assert spy and all(x.contract.right is Right.CALL for x in spy)
    assert qqq and all(x.contract.right is Right.PUT for x in qqq)


def test_black_scholes_sanity():
    call = bs_price(100, 100, 0.5, 0.3, 0.04, Right.CALL)
    put = bs_price(100, 100, 0.5, 0.3, 0.04, Right.PUT)
    assert 0 < put < call < 100
    assert math.isclose(call - put, 100 - 100 * math.exp(-0.04 * 0.5), rel_tol=1e-9)  # put-call parity
    assert bs_price(110, 100, 0, 0.3, 0.04, Right.CALL) == 10


def test_static_provider_follows_the_injected_clock():
    p = StaticDataProvider(clock)
    p.set_snapshot(snap(UP, [row()]))
    assert p.snapshot("AAA").as_of == NOW
    c = row().contract
    assert p.quotes_for([c])[0].timestamp_verified is True
    assert p.quotes_for([OptionContract("ZZZ", EXPIRY, Right.CALL, 1.0)]) == []


def test_yahoo_style_records_are_mapped_and_bad_rows_dropped():
    records = [
        {"strike": 100, "bid": 1.0, "ask": 1.2, "volume": 10, "openInterest": 50, "impliedVolatility": 0.4},
        {"strike": 105, "bid": float("nan"), "ask": 1.0},          # NaN bid
        {"strike": 110, "bid": 2.0, "ask": 1.0},                   # crossed
        {"strike": 115, "bid": 0.0, "ask": 0.0},                   # zero ask
        {"strike": -5, "bid": 1.0, "ask": 1.2},                    # bad strike
        {"strike": 120, "bid": 0.5, "ask": 0.7, "volume": float("nan"), "impliedVolatility": 50},
    ]
    rows = rows_from_records(records, "SPY", date(2027, 1, 15), Right.CALL)
    assert [r.contract.strike for r in rows] == [100.0, 120.0]
    assert rows[0].volume == 10 and rows[0].open_interest == 50 and rows[0].iv == 0.4
    assert rows[1].volume is None and rows[1].iv is None  # NaN volume and absurd IV become unknown, not guessed
