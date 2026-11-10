from datetime import date, timedelta

from helpers import CONTRACT, NOW, make_quote
from optplat.exits import EXIT, HOLD, UNOBSERVABLE, ExitPolicy, evaluate_exit
from optplat.models import OptionContract, Position, Right

POSITION = Position(CONTRACT, 4, 2.00)
POLICY = ExitPolicy()


def decide(quote, *, position=POSITION, entry_time=None, policy=POLICY):
    return evaluate_exit(position, quote, entry_time=entry_time, now=NOW, policy=policy)


def test_hold_inside_the_band():
    d = decide(make_quote(2.10, 2.20))
    assert d.action == HOLD and d.pnl_pct == 5.0


def test_take_profit():
    d = decide(make_quote(3.00, 3.10))
    assert (d.action, d.trigger, d.pnl_pct) == (EXIT, "take_profit", 50.0)


def test_stop_loss():
    d = decide(make_quote(1.30, 1.40))
    assert (d.action, d.trigger) == (EXIT, "stop_loss")


def test_exact_thresholds_trigger():
    assert decide(make_quote(2.80, 2.90)).trigger == "take_profit"  # +40%
    assert decide(make_quote(1.40, 1.50)).trigger == "stop_loss"    # -30%


def test_expiry_window_forces_an_exit():
    near = OptionContract("SPY", NOW.date() + timedelta(days=3), Right.CALL, 600.0)
    pos = Position(near, 1, 2.00)
    d = decide(make_quote(2.00, 2.10, contract=near), position=pos)
    assert (d.action, d.trigger) == (EXIT, "expiry_window")


def test_time_stop_is_disabled_by_default_and_needs_an_entry_time():
    old = NOW - timedelta(days=30)
    assert decide(make_quote(2.10, 2.20), entry_time=old).action == HOLD
    timed = ExitPolicy(max_days_held=5)
    assert decide(make_quote(2.10, 2.20), entry_time=old, policy=timed).trigger == "max_days_held"
    assert decide(make_quote(2.10, 2.20), entry_time=None, policy=timed).action == HOLD
    assert decide(make_quote(2.10, 2.20), entry_time=NOW - timedelta(days=1), policy=timed).action == HOLD


def test_unobservable_cases_are_never_a_silent_hold():
    assert decide(None).action == UNOBSERVABLE
    assert decide(make_quote(0.0, 0.10)).action == UNOBSERVABLE                       # zero bid
    assert decide(make_quote(2.20, 2.00)).action == UNOBSERVABLE                      # crossed
    assert decide(make_quote(2.00, 2.10, as_of=NOW - timedelta(seconds=300))).action == UNOBSERVABLE
    other = OptionContract("QQQ", date(2026, 12, 18), Right.CALL, 500.0)
    assert decide(make_quote(2.00, 2.10, contract=other)).action == UNOBSERVABLE
    assert decide(make_quote(2.00, 2.10), position=Position(CONTRACT, 1, 0.0)).action == UNOBSERVABLE
