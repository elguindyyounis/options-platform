import random
from datetime import date, timedelta

from optplat import lab
from optplat.marketdata import Bar


def bars_from(closes, start=date(2024, 1, 1)):
    out, d = [], start
    for c in closes:
        while d.weekday() >= 5:
            d += timedelta(days=1)
        out.append(Bar(d, c, 1_000_000))
        d += timedelta(days=1)
    return out


def walk(seed, n=400, drift=0.0, vol=0.01):
    rng, px, out = random.Random(seed), 100.0, []
    for _ in range(n):
        px *= 1 + drift + rng.gauss(0, vol)
        out.append(round(px, 4))
    return out


def test_wilson_interval_is_sane():
    assert lab.wilson(0, 0) is None
    lo, hi = lab.wilson(50, 100)
    assert lo < 50 < hi and 40 < lo and hi < 60
    assert lab.wilson(5, 10)[1] - lab.wilson(5, 10)[0] > lab.wilson(500, 1000)[1] - lab.wilson(500, 1000)[0]


def test_outcome_exits_on_stop_target_time_and_never_guesses_past_the_data():
    st = lab.Strategy("t", "", lambda c: True, stop_pct=5, target_pct=7.5, max_hold=3)
    assert lab.outcome([100, 100, 90], 0, st)[2] == "stop"
    assert lab.outcome([100, 101, 110], 0, st)[2] == "target"
    r = lab.outcome([100, 101, 102, 103], 0, st)
    assert r[2] == "time" and r[1] == 3
    assert lab.outcome([100, 101], 0, st) is None  # history ends before an exit: no trade, no guess
    assert lab.outcome([100, 110], 0, st)[0] < 10.0  # slippage is charged both ways


def test_entry_rule_only_sees_bars_up_to_the_entry_day():
    seen = []
    def spy(c):
        seen.append(len(c))
        return False
    st = lab.Strategy("t", "", spy)
    closes = walk(1, 120)
    lab.trades_for({"SPY": bars_from(closes)}, st, {})
    assert seen == list(range(lab.MIN_BARS, len(closes)))  # never the whole series at once


def test_results_do_not_change_when_future_bars_are_added_for_earlier_trades():
    st = lab.Strategy("t", "", lambda c: c[-1] > c[-2] > c[-3], 5, 7.5, 5)
    closes = walk(2, 300)
    early = lab.trades_for({"SPY": bars_from(closes[:200])}, st, {})
    late = lab.trades_for({"SPY": bars_from(closes)}, st, {})
    cut = bars_from(closes[:200])[-6].day
    assert [t for t in early if t["day"] < cut] == [t for t in late if t["day"] < cut]


def test_random_walk_is_not_proven_and_labelled_fictional():
    bars = {s: bars_from(walk(i)) for i, s in enumerate(["SPY", "QQQ", "IWM", "DIA", "AAPL", "MSFT"])}
    rep = lab.evaluate(bars, fictional=True)
    assert rep["fictional"] and "FICTIONAL" in rep["note"] and rep["strategies_tried"] == len(lab.STRATEGIES)
    assert all(r["verdict"] == "NOT_PROVEN" and r["reasons"] for r in rep["results"])  # no edge exists in a coin flip
    assert rep == lab.evaluate(bars, fictional=True)  # deterministic: same data, same answer


def test_a_planted_edge_can_pass_and_needs_every_condition():
    # every bar after a "signal" day (a close that is exactly 100.0 above the previous) rises: the rule really works
    rng, closes = random.Random(3), []
    px = 100.0
    for i in range(600):
        if i % 7 == 0:
            px *= 1.001
            closes.append(px)
            closes.append(px)  # marker: two equal closes in a row
            for _ in range(4):
                px *= 1.02
                closes.append(px)
        else:
            px *= 1 + rng.gauss(0, 0.002)
            closes.append(px)
    st = lab.Strategy("planted", "", lambda c: c[-1] == c[-2], 5, 7.5, 4)
    bars = {s: bars_from(closes) for s in ("SPY", "QQQ", "AAPL")}
    rep = lab.evaluate(bars, fictional=True, strategies=(st,))
    r = rep["results"][0]
    assert r["all"]["win_rate_pct"] > 80 and r["random"]["p_value"] <= 0.05
    thin = lab.evaluate({"SPY": bars_from(closes[:90])}, fictional=True, strategies=(st,))["results"][0]
    assert thin["verdict"] == "NOT_PROVEN" and any("independent entry days" in w for w in thin["reasons"])


def test_regimes_are_reported_and_small_groups_are_flagged():
    bars = {s: bars_from(walk(i)) for i, s in enumerate(["SPY", "QQQ"])}
    r = lab.evaluate(bars, True)["results"][0]
    assert set(r["by_regime"]) <= {"UP", "DOWN", "UNKNOWN"} and all("enough" in v for v in r["by_regime"].values())


def test_lab_endpoints_need_the_token_and_store_the_report():
    from fastapi.testclient import TestClient
    from optplat.api import create_app
    from test_scanner import build_engine

    manager, engine = build_engine()
    tok = "t" * 24
    with TestClient(create_app(manager, tok, engine)) as c:
        assert c.get("/api/lab").status_code == 401 and c.post("/api/lab/run").status_code == 401
        h = {"X-API-Token": tok}
        assert c.get("/api/lab", headers=h).json() is None  # nothing invented before a run
        run = c.post("/api/lab/run", headers=h)
        assert run.status_code in (200, 502)
        if run.status_code == 200:
            assert c.get("/api/lab", headers=h).json()["strategies_tried"] == len(lab.STRATEGIES)
