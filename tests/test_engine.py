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
    engine, manager, broker, *_ = build(auto_entries=True, enforce_market_hours=False)
    engine.manager.clock.now = SATURDAY
    report = engine.run_cycle()
    assert report["market_open"] is False and report["trading_allowed"] is True
    assert report["entries"][0]["result"] == "FILLED"


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


def test_no_proposal_entry_carries_a_plain_reason():
    engine, manager, broker, *_ = build(auto_entries=True)
    engine.run_cycle()
    again = engine.run_cycle()
    entry = again["entries"][0]
    assert entry["result"] == "NO_PROPOSAL"
    assert isinstance(entry["reason"], str) and entry["reason"]


def test_cycle_report_lists_ranked_candidates_without_trading_on_them():
    engine, manager, broker, *_ = build(auto_entries=True)
    report = engine.run_cycle()
    cands = report["candidates"]
    assert cands and len(cands) <= 10
    assert [c["score"] for c in cands] == sorted((c["score"] for c in cands), reverse=True)
    assert {"symbol", "contract", "score", "limit_price", "trend", "spread_pct", "dte", "volume", "open_interest"} <= set(cands[0])
    assert len(manager.list()) <= len(report["entries"])  # candidates are never extra orders


def test_runner_status_reports_health_and_stall_server_side():
    from datetime import datetime, timedelta, timezone

    engine, *_ = build()
    runner = Runner(engine)
    idle = runner.status()
    assert idle["running"] is False and idle["stalled"] is False and idle["last_success_at"] is None
    runner.start()
    deadline = time.time() + 5
    while runner.last_success_at is None and time.time() < deadline:
        time.sleep(0.05)
    try:
        live = runner.status()
        assert live["running"] and live["last_success_at"] and live["consecutive_failures"] == 0
        assert live["stalled"] is False
        interval = engine.config().interval_s
        late = runner.status(now=runner.last_success_at + timedelta(seconds=3 * interval + 1))
        assert late["stalled"] is True and late["seconds_since_success"] > 3 * interval
    finally:
        runner.stop()


def test_runner_failures_are_counted_and_reset_on_success():
    engine, *_ = build()
    runner = Runner(engine)
    calls = {"n": 0}
    real = engine.run_cycle

    def flaky():
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("boom")
        return real()

    class OneShotStop:
        """Stops the loop after the given number of waits, without real sleeping."""

        def __init__(self, waits):
            self.waits = waits

        def is_set(self):
            return self.waits <= 0

        def wait(self, _timeout):
            self.waits -= 1

    engine.run_cycle = flaky  # type: ignore[method-assign]
    runner._stop = OneShotStop(1)  # type: ignore[assignment]
    runner._loop()  # first pass fails
    assert runner.consecutive_failures == 1 and "boom" in runner.last_error
    assert runner.last_failure_at is not None and runner.last_success_at is None
    runner._stop = OneShotStop(1)  # type: ignore[assignment]
    runner._loop()  # second pass succeeds
    assert runner.consecutive_failures == 0 and runner.last_error is None
    assert runner.last_success_at is not None and runner.last_failure_at is not None


def test_recent_outcomes_tally_entry_results_across_cycles_and_is_bounded():
    from optplat import engine as eng

    engine, *_ = build(auto_entries=True)
    assert engine.status()["recent_outcomes"] == {"cycles": 0, "window": eng.OUTCOME_WINDOW, "counts": {}}
    engine.run_cycle()
    engine.run_cycle()
    out = engine.status()["recent_outcomes"]
    assert out["cycles"] == 2 and sum(out["counts"].values()) >= 2
    assert out["counts"].get("NO_PROPOSAL", 0) >= 1  # second cycle: already holding the contract
    engine.store.set_state("outcome_history", "not json")  # corrupt history must never break status
    assert engine.status()["recent_outcomes"]["cycles"] == 0
    for _ in range(eng.OUTCOME_WINDOW + 3):
        engine.run_cycle()
    assert engine.status()["recent_outcomes"]["cycles"] == eng.OUTCOME_WINDOW


def test_dashboard_outcome_line_uses_text_nodes_only():
    from pathlib import Path

    js = (Path(__file__).parent.parent / "src/optplat/static/app.js").read_text()
    assert "outcomesLine" in js and "innerHTML" not in js


# ---------------------------------------------------------------- exit plans (display only)
def test_exit_plans_show_sell_levels_for_open_positions():
    engine, manager, broker, provider, clock = build(auto_entries=True, auto_exits=True)
    assert engine.status()["exit_plans"] == []
    engine.run_cycle()
    pos = broker.get_positions()[0]
    plan = engine.status()["exit_plans"][0]
    assert plan["contract"] == pos.contract.occ_symbol.strip()
    assert plan["take_profit_bid"] == round(pos.avg_cost * 1.40, 2)
    assert plan["stop_loss_bid"] == round(pos.avg_cost * 0.70, 2)
    assert plan["days_to_expiry"] == 60 and plan["expiry_exit_within_days"] == 5


def test_exit_plan_levels_follow_config_and_bad_cost_is_none():
    from optplat.exits import ExitPolicy, exit_plan
    from optplat.models import Position

    c = contract()
    pol = ExitPolicy(take_profit_pct=50.0, stop_loss_pct=20.0)
    good = exit_plan(Position(c, 1, 2.0), pol, NOW)
    assert (good["take_profit_bid"], good["stop_loss_bid"]) == (3.0, 1.6)
    bad = exit_plan(Position(c, 1, float("nan")), pol, NOW)
    assert bad["take_profit_bid"] is None and bad["stop_loss_bid"] is None


def test_dashboard_positions_table_states_exit_levels_with_text_only():
    from pathlib import Path

    js = (Path(__file__).parent.parent / "src/optplat/static/app.js").read_text()
    assert "Take-profit when bid reaches" in js and "Automatic exits are OFF" in js and "innerHTML" not in js


def test_entry_reports_size_vs_liquidity_without_changing_the_order():
    from optplat.liquidity import size_vs_liquidity

    engine, manager, *_ = build(auto_entries=True)
    entry = engine.run_cycle()["entries"][0]
    sl = entry["size_vs_liquidity"]
    assert sl["quantity"] == entry["quantity"]
    assert sl["pct_of_volume"] == round(entry["quantity"] / 200 * 100, 2)
    assert "Display only" in sl["note"]
    big = size_vs_liquidity(30, 200, 2000)
    assert any("over 10%" in w for w in big["warnings"])
    assert size_vs_liquidity(1, None, 0)["pct_of_volume"] is None
    assert len(size_vs_liquidity(1, None, 0)["warnings"]) == 2
    assert size_vs_liquidity(1, 200, 2000)["warnings"] == []
