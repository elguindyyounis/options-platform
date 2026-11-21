from dataclasses import replace
from datetime import date, datetime, timedelta, timezone

import pytest

import test_optionlanes as tol
from optplat import forecast as fc
from optplat import optionlanes as ol
from optplat.marketdata import Bar
from optplat.store import Store

NOW = datetime(2026, 11, 20, 15, 0, tzinfo=timezone.utc)


class Fake:
    """Stands in for Kronos: forecasts a fixed move per symbol, and counts how often it was asked."""
    name = "fake-kronos"

    def __init__(self, moves, ok=True, boom=None):
        self.moves, self.ok, self.boom, self.asked = moves, ok, boom, []

    def status(self):
        return (True, "ready") if self.ok else (False, "Kronos is not installed (fake)")

    def predict(self, symbol, bars, horizon, now):
        self.asked.append(symbol)
        if self.boom:
            raise RuntimeError(self.boom)
        last = bars[-1]
        close = last.close * (1 + self.moves.get(symbol, 0.0) / 100)
        return fc.make_forecast(symbol, last, self.name, horizon, now, close, max(close, last.close) * 1.002, min(close, last.close) * 0.998)


def lane(moves, names=("SPY", "QQQ"), forecaster=None, **over):
    data, now = tol.downtrend_daily(names)
    p = replace(ol.KRONOS, symbols=names, budget_usd=20000.0, **over)
    ln, prov, store, box = tol.make(p, daily=data, now=now)
    ln.forecaster = forecaster if forecaster is not None else Fake(moves)
    return ln, prov, store


# ---------------------------------------------------------------- the pieces
def test_future_days_skips_weekends():
    assert fc.future_days(date(2026, 11, 20), 3) == [date(2026, 11, 23), date(2026, 11, 24), date(2026, 11, 25)]


def test_a_forecast_with_nonsense_numbers_is_refused_and_never_journaled():
    last = Bar(date(2026, 11, 20), 100.0, 1e6)
    good = fc.make_forecast("SPY", last, "m", 3, NOW, 101.0, 102.0, 99.5)
    assert good and round(good.move_pct, 1) == 1.0
    for bad in ((float("nan"), 102, 99), (101, 99, 102), (-1, 102, 99), (105, 102, 99), (101, float("inf"), 99)):
        assert fc.make_forecast("SPY", last, "m", 3, NOW, *bad) is None


def test_kronos_reports_it_is_not_installed_instead_of_raising(tmp_path):
    k = fc.KronosForecaster(path=str(tmp_path / "nowhere"))
    ok, why = k.status()
    assert not ok and "install-kronos.sh" in why
    assert k.predict("SPY", [Bar(date(2026, 11, 20), 100.0, 1e6)], 3, NOW) is None     # too few candles: a definitive no, no model needed


def test_only_bars_with_a_full_candle_count():
    full = Bar(date(2026, 11, 19), 100.0, 1e6, 99.0, 101.0, 98.0)
    assert fc.has_candles([full, Bar(date(2026, 11, 20), 100.0, 1e6)]) == [full]


def test_the_switch_is_off_until_installed_or_asked_for_and_zero_forces_it_off(monkeypatch, tmp_path):
    monkeypatch.setenv("OPTPLAT_KRONOS_PATH", str(tmp_path / "nowhere"))
    monkeypatch.delenv("OPTPLAT_KRONOS", raising=False)
    assert fc.from_env() is None                                       # nothing installed, nothing asked for
    monkeypatch.setenv("OPTPLAT_KRONOS", "1")
    assert isinstance(fc.from_env(), fc.KronosForecaster)              # asked for: on, and status() will say what is missing
    (tmp_path / "clone" / "model").mkdir(parents=True)
    (tmp_path / "clone" / "model" / "kronos.py").write_text("")
    monkeypatch.setenv("OPTPLAT_KRONOS_PATH", str(tmp_path / "clone"))
    monkeypatch.delenv("OPTPLAT_KRONOS")
    assert isinstance(fc.from_env(), fc.KronosForecaster)              # installed: on
    monkeypatch.setenv("OPTPLAT_KRONOS", "0")
    assert fc.from_env() is None


# ---------------------------------------------------------------- the lane
def test_the_kronos_lane_copies_the_swing_base_lane_except_for_where_the_signal_comes_from():
    b, k = ol.SWING_BASE, ol.KRONOS
    same = ("budget_usd", "max_open", "max_per_sector", "dte_min", "dte_max", "otm_pct", "max_spread_pct", "min_oi", "min_volume", "min_ask",
            "stop_pct", "target_pct", "max_hold_bars", "experimental", "earnings_gate", "symbols", "max_per_name", "stack")
    assert all(getattr(k, f) == getattr(b, f) for f in same) and k.signal == "kronos" and k in ol.ALL_PARAMS


def test_a_forecast_of_a_rise_buys_a_call_a_forecast_of_a_fall_buys_a_put_and_a_small_one_does_nothing_but_is_journaled():
    ln, prov, store = lane({"SPY": 2.0, "QQQ": -2.0, "IWM": 0.4}, names=("SPY", "QQQ", "IWM"))
    ln.step(force=True)
    trades = {t["symbol"]: t for t in tol.opened(ln, prov, store)}
    assert trades["SPY"]["open_payload"]["right"] == "C" and trades["QQQ"]["open_payload"]["right"] == "P" and "IWM" not in trades
    assert trades["SPY"]["open_payload"]["signal"]["forecast"]["move_pct"] == 2.0           # the forecast is stored with the trade
    logged = {f["symbol"]: f for f in store.forecasts(prov.fictional)}
    assert set(logged) == {"SPY", "QQQ", "IWM"} and logged["IWM"]["realized_close"] is None


def test_each_bar_is_forecast_once_and_a_second_check_does_not_ask_again():
    f = Fake({"SPY": 2.0})
    ln, prov, store = lane({}, names=("SPY",), forecaster=f)
    ln.step(force=True)
    ln.step(force=True)
    assert f.asked == ["SPY"] and len(store.forecasts(prov.fictional)) == 1 and len(tol.opened(ln, prov, store)) == 1


def test_without_a_working_model_the_lane_does_nothing_says_why_and_keeps_the_day_for_later():
    f = Fake({"SPY": 5.0}, ok=False)
    ln, prov, store = lane({}, names=("SPY",), forecaster=f)
    out = ln.step(force=True)
    assert tol.opened(ln, prov, store) == [] and f.asked == [] and any("not installed" in s for s in out["skips"])
    f.ok = True
    ln.step(force=True)
    assert len(tol.opened(ln, prov, store)) == 1                       # nothing was used up while the model was missing


def test_a_lane_with_no_forecaster_at_all_says_it_is_switched_off():
    ln, prov, store = lane({}, names=("SPY",))
    ln.forecaster = None
    out = ln.step(force=True)
    assert tol.opened(ln, prov, store) == [] and any("switched off" in s for s in out["skips"])


def test_a_model_that_raises_is_reported_and_retried_without_stopping_the_lane():
    f = Fake({"SPY": 5.0}, boom="out of memory")
    ln, prov, store = lane({}, names=("SPY",), forecaster=f)
    out = ln.step(force=True)
    assert tol.opened(ln, prov, store) == [] and any("out of memory" in e for e in out["errors"]) and store.forecasts(prov.fictional) == []
    f.boom = None
    ln.step(force=True)
    assert len(tol.opened(ln, prov, store)) == 1


def test_only_a_few_forecasts_are_made_per_check_so_a_slow_model_cannot_stall_the_engine():
    names = ("SPY", "QQQ", "IWM", "DIA", "TLT", "HYG", "GLD", "XLK")
    f = Fake({})
    ln, prov, store = lane({}, names=names, forecaster=f)
    ln.step(force=True)
    assert len(f.asked) == ol.KRONOS_MAX_PER_STEP
    ln.step(force=True)
    assert sorted(f.asked) == sorted(names)


# ---------------------------------------------------------------- the scorecard
def logged(store, i, move, realized_move, last=100.0):
    f = {"symbol": f"S{i}", "bar_day": "2026-11-01", "model": "m", "horizon": 3, "made_at": NOW.isoformat(), "last_close": last,
         "pred_close": last * (1 + move / 100), "pred_high": last * 1.05, "pred_low": last * 0.9}
    store.record_forecast(f, False)
    row = store.forecasts(False)[0]
    store.resolve_forecast(row["id"], last * (1 + realized_move / 100), "2026-11-04")


def test_the_scorecard_withholds_a_verdict_below_the_minimum():
    s = Store(":memory:")
    for i in range(5):
        logged(s, i, 1.0, 1.0)
    out = fc.scorecard(s, False)
    assert out["verdict"] == "too_few" and out["scored"] == 5 and "A verdict needs 20" in out["headline"]
    assert fc.scorecard(Store(":memory:"), False)["headline"] == "No forecasts have been made yet."


def test_a_forecaster_that_is_right_and_closer_than_no_change_is_ahead_but_never_called_proof():
    s = Store(":memory:")
    for i in range(30):
        up = i % 2 == 0
        logged(s, i, 1.0 if up else -1.0, 1.2 if up else -1.2)         # right way, and much closer than "no change"
    out = fc.scorecard(s, False)
    assert out["verdict"] == "ahead" and out["mae_pct"] < out["mae_no_change_pct"] and "Not proof" in out["headline"]


def test_a_forecaster_no_better_than_always_up_is_called_behind():
    s = Store(":memory:")
    for i in range(30):
        logged(s, i, 1.0, 1.0 if i % 2 == 0 else -1.0)                  # always forecasts up; half of them are wrong
    out = fc.scorecard(s, False)
    assert out["verdict"] == "behind" and out["direction_hit_pct"] == 50.0


def test_resolve_scores_a_forecast_once_its_horizon_has_passed_and_not_before():
    s = Store(":memory:")
    bars = tol.mk([0.001] * 30)
    day = bars[-4].day
    s.record_forecast({"symbol": "SPY", "bar_day": day.isoformat(), "model": "m", "horizon": 3, "made_at": NOW.isoformat(), "last_close": bars[-4].close,
                       "pred_close": bars[-4].close * 1.01, "pred_high": bars[-4].close * 1.02, "pred_low": bars[-4].close * 0.99}, False)
    s.record_forecast({"symbol": "SPY", "bar_day": bars[-2].day.isoformat(), "model": "m", "horizon": 3, "made_at": NOW.isoformat(), "last_close": bars[-2].close,
                       "pred_close": bars[-2].close, "pred_high": bars[-2].close, "pred_low": bars[-2].close}, False)
    assert fc.resolve(s, {"SPY": bars}, False) == 1                      # the second forecast is only 1 bar old
    done = [f for f in s.forecasts(False) if f["realized_close"] is not None]
    assert len(done) == 1 and done[0]["realized_close"] == bars[-1].close and done[0]["resolved_day"] == bars[-1].day.isoformat()


# ---------------------------------------------------------------- the endpoint and the page
def test_the_forecast_endpoint_needs_the_token_and_says_the_model_is_off_when_it_is(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient

    from optplat.api import create_app
    from optplat.broker import SimBroker
    from optplat.engine import EngineConfig, TradingEngine
    from optplat.marketdata import DemoDataProvider
    from optplat.orders import OrderManager
    from optplat.strategy import LiquidTrendStrategy

    monkeypatch.setenv("OPTPLAT_KRONOS_PATH", str(tmp_path / "nowhere"))
    monkeypatch.delenv("OPTPLAT_KRONOS", raising=False)
    manager = OrderManager(SimBroker(), Store(":memory:"))
    engine = TradingEngine(manager, DemoDataProvider(), LiquidTrendStrategy(), default_config=EngineConfig())
    with TestClient(create_app(manager, "t" * 24, engine, None)) as c:
        assert c.get("/api/forecasts").status_code == 401
        body = c.get("/api/forecasts", headers={"X-API-Token": "t" * 24}).json()
        page = c.get("/").text, c.get("/static/app.js").text
    assert body["model_ready"] is False and "install-kronos.sh" in body["model_status"] and body["logged"] == 0 and body["verdict"] == "none"
    assert 'id="rs-fc-table"' in page[0] and "/api/forecasts" in page[1] and "renderForecasts" in page[1]
