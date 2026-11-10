from datetime import timedelta

from helpers import CONTRACT, NOW, make_intent, make_quote
from optplat.models import Account, OptionContract, Position, Right
from optplat.risk import RiskPolicy, evaluate

POLICY = RiskPolicy()
ACCOUNT = Account(equity=100_000, cash=100_000, open_premium=0)


def run(intent=None, quote="default", account=ACCOUNT, positions=(), policy=POLICY, kill=False):
    if quote == "default":
        quote = make_quote()
    return evaluate(intent or make_intent(), quote, account, positions, policy, now=NOW, kill_switch=kill)


def test_good_order_is_allowed():
    decision = run()
    assert decision.allowed, decision.failures
    assert decision.worst_case_cost == 808.0


def test_kill_switch_blocks():
    assert "Kill switch is active" in run(kill=True).failures


def test_missing_quote_fails_closed():
    assert "No broker quote available" in run(quote=None).failures


def test_quote_for_other_contract_fails():
    other = OptionContract("SPY", CONTRACT.expiry, Right.PUT, 600.0)
    assert "Quote is for a different contract" in run(quote=make_quote(contract=other)).failures


def test_stale_quote_fails():
    stale = make_quote(as_of=NOW - timedelta(seconds=120))
    assert any("stale" in f for f in run(quote=stale).failures)


def test_future_quote_fails():
    future = make_quote(as_of=NOW + timedelta(seconds=120))
    assert any("stale or from the future" in f for f in run(quote=future).failures)


def test_unverified_quote_time_fails_by_default():
    assert any("not verified" in f for f in run(quote=make_quote(verified=False)).failures)


def test_unverified_quote_time_can_be_allowed_by_policy():
    lenient = RiskPolicy(require_verified_quote_time=False)
    assert run(quote=make_quote(verified=False), policy=lenient).allowed


def test_wide_spread_fails():
    assert any("Spread" in f for f in run(quote=make_quote(1.00, 2.00)).failures)


def test_zero_bid_fails():
    assert any("Zero bid" in f for f in run(quote=make_quote(0.0, 0.10), intent=make_intent(limit=0.10)).failures)


def test_crossed_quote_is_invalid():
    assert "Invalid two-sided quote" in run(quote=make_quote(2.10, 2.00)).failures


def test_limit_far_above_ask_fails():
    assert any("exceeds the ask" in f for f in run(intent=make_intent(limit=2.50)).failures)


def test_position_size_limit():
    assert run(intent=make_intent(qty=4)).allowed
    assert "Exceeds per-position premium limit" in run(intent=make_intent(qty=5)).failures


def test_aggregate_premium_limit():
    heavy = Account(equity=100_000, cash=100_000, open_premium=9_500)
    assert "Exceeds aggregate open premium limit" in run(account=heavy).failures


def test_insufficient_cash():
    poor = Account(equity=100_000, cash=100, open_premium=0)
    assert "Insufficient cash" in run(account=poor).failures


def test_duplicate_open_contract():
    held = [Position(CONTRACT, 1, 2.0)]
    assert "Duplicate open contract" in run(positions=held).failures


def test_max_open_positions():
    other = [
        Position(OptionContract("QQQ", CONTRACT.expiry, Right.CALL, 500.0 + i), 1, 1.0) for i in range(12)
    ]
    assert "Maximum open positions reached" in run(positions=other).failures


def test_dte_bounds():
    near = OptionContract("SPY", NOW.date() + timedelta(days=3), Right.CALL, 600.0)
    assert any("Days to expiry" in f for f in run(intent=make_intent(contract=near), quote=make_quote(contract=near)).failures)


def test_bad_quantities_are_rejected():
    for qty in (0, -1, 101, True, 1.5):
        decision = run(intent=make_intent(qty=qty))
        assert not decision.allowed, qty


def test_bad_prices_are_rejected():
    for price in (0, -1, float("nan"), float("inf")):
        decision = run(intent=make_intent(limit=price))
        assert "Limit price must be a positive, finite number" in decision.failures, price


def test_nonstandard_multiplier_rejected():
    odd = OptionContract("SPY", CONTRACT.expiry, Right.CALL, 600.0, multiplier=10)
    assert "Only standard 100-share contracts are supported" in run(
        intent=make_intent(contract=odd), quote=make_quote(contract=odd)
    ).failures


def test_non_positive_equity_rejected():
    broke = Account(equity=0, cash=0, open_premium=0)
    assert "Account equity unavailable or non-positive" in run(account=broke).failures
