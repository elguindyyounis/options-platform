import time
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from helpers import NOW
from optplat.broker import SimBroker
from optplat.engine import EngineConfig, Runner, TradingEngine, size_quantity
from optplat.marketdata import ChainRow, MarketSnapshot, StaticDataProvider
from optplat.models import Account, OptionContract, OrderState, Right
from optplat.orders import OrderManager
from optplat.risk import RiskPolicy
from optplat.store import Store
from optplat.strategy import LiquidTrendStrategy

EXPIRY = NOW.date() + timedelta(days=60)
UP = tuple(100.0 + i for i in range(60))
SATURDAY = datetime(2026, 11, 21, 15, 0, tzinfo=timezone.utc)


class Clock:
    def __init__(self):
        self.now = NOW

    def __call__(self):
        return self.now


def snapshot(symbol="AAA", bid=4.90, ask=5.10, strike=160.0, oi=2000):
    contract = OptionContract(symbol, EXPIRY, Right.CALL, strike)
    return MarketSnapshot(symbol, UP[-1], UP, (ChainRow(contract, bid, ask, 200, oi, 0.3),), NOW, "test", True)


def build(symbols=("AAA",), **config):
    clock = Clock()
    provider = StaticDataProvider(clock)
    for s in symbols:
        provider.set_snapshot(snapshot(s))
    broker = SimBroker()
    manager = OrderManager(broker, Store(":memory:"), clock=clock)
    engine = TradingEngine(manager, provider, LiquidTrendStrategy(), clock=clock)
    engine.set_config({"watchlist": list(symbols), **config})
    return engine, manager, broker, provider, clock


def contract(symbol="AAA"):
    return OptionContract(symbol, EXPIRY, Right.CALL, 160.0)


# ---------------------------------------------------------------- config
def test_defaults_are_safe():
    cfg = EngineConfig()
    assert cfg.auto_entries is False and cfg.auto_exits is True


def test_entries_cannot_be_enabled_without_exits():
    engine, *_ = build()
    with pytest.raises(ValueError, match="auto_entries requires auto_exits"):
        engine.set_config({"auto_entries": True, "auto_exits": False})
    assert engine.config().auto_entries is False  # nothing was persisted


@pytest.mark.parametrize(
    "changes",
    [
        {"watchlist": ["spy; drop table"]},
        {"watchlist": []},
        {"interval_s": 1},
        {"stop_loss_pct": 0},
        {"max_new_per_cycle": 99},
        {"auto_entries": "yes"},
    ],
)
def test_bad_config_is_rejected(changes):
    engine, *_ = build()
    with pytest.raises(ValueError):
        engine.set_config(changes)


def test_watchlist_is_normalised_and_deduplicated():
    engine, *_ = build()
    assert engine.set_config({"watchlist": "spy, qqq  SPY"}).watchlist == ("SPY", "QQQ")


def test_corrupt_stored_config_falls_back_to_defaults():
    engine, manager, *_ = build()
    manager.store.set_state("engine_config", "{not json")
    assert engine.config() == EngineConfig()


def test_size_quantity_respects_budget_cash_and_cap():
    policy = RiskPolicy()
    rich = Account(100_000, 100_000, 0)
    assert size_quantity(rich, policy, 5.15) == 1       # $1,000 budget / $515
    assert size_quantity(rich, policy, 2.50) == 4
    assert size_quantity(rich, policy, 11.00) == 0
    assert size_quantity(Account(100_000, 300, 0), policy, 2.50) == 1  # cash is the limit
    assert size_quantity(rich, policy, float("nan")) == 0
    assert size_quantity(Account(0, 0, 0), policy, 1.0) == 0


# ---------------------------------------------------------------- entries
def test_entries_are_off_by_default():
    engine, manager, broker, *_ = build()
    report = engine.run_cycle()
    assert report["entries"] == [] and "off" in report["entries_note"]
    assert manager.list() == []


def test_cycle_opens_one_position_and_never_doubles_up():
    engine, manager, broker, *_ = build(auto_entries=True)
    first = engine.run_cycle()
    assert first["entries"][0]["result"] == "FILLED" and first["entries"][0]["quantity"] == 1
    assert len(broker.get_positions()) == 1
    again = engine.run_cycle()
    assert again["entries"][0]["result"] == "NO_PROPOSAL"
    assert len(manager.list()) == 1


def test_max_new_per_cycle_is_honoured():
    engine, manager, broker, *_ = build(symbols=("AAA", "BBB"), auto_entries=True, max_new_per_cycle=1)
    report = engine.run_cycle()
    assert len(report["entries"]) == 1 and len(broker.get_positions()) == 1
    engine.set_config({"max_new_per_cycle": 2})
    engine.run_cycle()
    assert len(broker.get_positions()) == 2


def test_unaffordable_proposals_are_skipped_with_a_reason():
    engine, manager, broker, provider, _ = build(auto_entries=True)
    provider.set_snapshot(snapshot(bid=19.9, ask=20.1))  # $2,000+ per contract against a $1,000 cap
    report = engine.run_cycle()
    assert report["entries"][0]["result"] == "NOTHING_AFFORDABLE_WITHIN_SIZE_CAP"


def test_market_closed_blocks_entries_and_defers_exits():
    engine, manager, broker, provider, clock = build(auto_entries=True)
    engine.run_cycle()
    clock.now = SATURDAY
    provider.set_snapshot(snapshot(bid=7.5, ask=7.7))
    report = engine.run_cycle()
    assert "Market closed" in report["entries_note"]
    assert report["exits"][0]["action"] == "EXIT"
    assert report["exits"][0]["result"] == "DEFERRED_MARKET_CLOSED"
    assert len(broker.get_positions()) == 1


def test_market_hours_enforcement_can_be_switched_off_for_demos():
    engine, manager, broker, provider, _ = build(auto_entries=True, enforce_market_hours=False)
    provider.fictional = True  # only fictional data may run outside the session
    engine.manager.clock.now = SATURDAY
    report = engine.run_cycle()
    assert report["market_open"] is False and report["trading_allowed"] is True
    assert report["entries"][0]["result"] == "FILLED"


def test_market_hours_cannot_be_switched_off_for_real_data():
    engine, manager, broker, provider, clock = build(auto_entries=True, enforce_market_hours=False)
    assert provider.fictional is False
    clock.now = SATURDAY
    report = engine.run_cycle()
    assert report["market_open"] is False and report["trading_allowed"] is False
    assert "Market closed" in report["entries_note"] and broker.get_positions() == []
    assert engine.status()["market"]["hours_enforced"] is True


def test_market_hours_switch_is_honoured_only_for_fictional_data():
    engine, _, _, provider, _ = build(enforce_market_hours=False)
    assert engine.status()["market"]["hours_enforced"] is True
    provider.fictional = True
    assert engine.status()["market"]["hours_enforced"] is False


def test_kill_switch_blocks_entries():
    engine, manager, broker, *_ = build(auto_entries=True)
    manager.set_kill_switch(True)
    report = engine.run_cycle()
    assert "Kill switch" in report["entries_note"] and broker.get_positions() == []


# ---------------------------------------------------------------- exits
def test_take_profit_exit_then_cooldown_blocks_re_entry():
    engine, manager, broker, provider, clock = build(auto_entries=True)
    engine.run_cycle()
    provider.set_snapshot(snapshot(bid=7.5, ask=7.7))
    report = engine.run_cycle()
    item = report["exits"][0]
    assert (item["action"], item["trigger"], item["result"]) == ("EXIT", "take_profit", "FILLED")
    assert broker.get_positions() == []
    assert manager.report()["realized_pnl"] == 233.0
    again = engine.run_cycle()
    assert again["entries"][0]["result"] == "NO_PROPOSAL"  # sold moments ago: cooling down
    assert broker.get_positions() == []
    engine.set_config({"reentry_cooldown_s": 0})
    # Same 15-minute window with different terms: the idempotency guard refuses to reuse the key.
    assert engine.run_cycle()["entries"][0]["result"] == "KEY_CONFLICT"
    clock.now = NOW + timedelta(seconds=1000)  # a new window: a fresh, legitimate order
    assert engine.run_cycle()["entries"][0]["result"] == "FILLED"


def test_stop_loss_exit():
    engine, manager, broker, provider, _ = build(auto_entries=True)
    engine.run_cycle()
    provider.set_snapshot(snapshot(bid=3.0, ask=3.2))
    item = engine.run_cycle()["exits"][0]
    assert (item["trigger"], item["result"]) == ("stop_loss", "FILLED")


def test_exits_off_means_shadow_only():
    engine, manager, broker, provider, _ = build(auto_entries=True)
    engine.run_cycle()
    engine.set_config({"auto_entries": False, "auto_exits": False})
    provider.set_snapshot(snapshot(bid=7.5, ask=7.7))
    item = engine.run_cycle()["exits"][0]
    assert item["action"] == "EXIT" and item["result"] == "SHADOW_ONLY_AUTO_EXITS_OFF"
    assert len(broker.get_positions()) == 1


def test_kill_switch_does_not_stop_exits():
    engine, manager, broker, provider, _ = build(auto_entries=True)
    engine.run_cycle()
    manager.set_kill_switch(True)
    provider.set_snapshot(snapshot(bid=7.5, ask=7.7))
    assert engine.run_cycle()["exits"][0]["result"] == "FILLED"


def test_unpriceable_position_pauses_entries():
    engine, manager, broker, provider, _ = build(symbols=("AAA", "BBB"), auto_entries=True)
    engine.run_cycle()
    provider.set_snapshot(snapshot(bid=0.0, ask=7.7))
    report = engine.run_cycle()
    assert report["exits"][0]["action"] == "UNOBSERVABLE"
    assert "entries paused" in report["entries_note"]
    assert len(broker.get_positions()) == 1


def test_resting_exit_is_not_duplicated_on_the_next_cycle():
    engine, manager, broker, provider, clock = build(auto_entries=True)
    engine.run_cycle()
    provider.set_snapshot(snapshot(bid=7.5, ask=7.7))
    # Make the sim unable to fill: no bid-side liquidity at the engine's limit
    broker.slippage_pct = 10.0
    first = engine.run_cycle()["exits"][0]
    assert first["result"] == "SUBMITTED"
    second = engine.run_cycle()["exits"][0]
    assert second["result"] in ("ALREADY_CLOSING", "SUBMITTED")
    sells = [o for o in manager.list() if o.intent.side.value == "SELL_TO_CLOSE"]
    assert len(sells) == 1


# ---------------------------------------------------------------- housekeeping
def test_stale_resting_orders_are_cancelled():
    engine, manager, broker, provider, clock = build()
    engine.run_cycle()  # syncs quotes into the sim broker
    from helpers import make_intent, make_quote

    c = contract()
    order = manager.submit(make_intent("rest-00000001", qty=1, limit=1.00, contract=c))
    assert order.state is OrderState.SUBMITTED
    clock.now = NOW + timedelta(seconds=1200)
    report = engine.run_cycle()
    assert report["cancelled_stale"] == [order.id]
    assert manager.get(order.id).state is OrderState.CANCELLED


def test_one_failing_data_source_does_not_stop_the_cycle():
    engine, manager, broker, provider, _ = build(auto_entries=True)
    engine.set_config({"watchlist": ["MISSING", "AAA"]})  # MISSING has no snapshot in the provider
    report = engine.run_cycle()
    assert any("MISSING" in e for e in report["errors"])
    assert len(broker.get_positions()) == 1


def test_cycle_report_is_persisted():
    engine, *_ = build()
    report = engine.run_cycle()
    assert engine.last_cycle()["started_at"] == report["started_at"]
    status = engine.status()
    assert status["config"]["auto_entries"] is False and status["kill_switch"] is False


def test_runner_starts_runs_a_cycle_and_stops():
    engine, *_ = build()
    runner = Runner(engine)
    assert not runner.running()
    runner.start()
    deadline = time.time() + 5
    while engine.last_cycle() is None and time.time() < deadline:
        time.sleep(0.05)
    assert engine.last_cycle() is not None and runner.running()
    runner.stop()
    assert not runner.running() and runner.last_error is None
