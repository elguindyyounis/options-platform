from datetime import timedelta

from optplat import swing as sw
from optplat import swing_replay as rp
from optplat.marketdata import DemoDataProvider

from tests.test_swing import mk, pullback_rets  # noqa: E402


def history(extra=()):
    """A long uptrend with repeated pullbacks, so the rule has something to trade."""
    rets = []
    for seed in range(4):
        rets += pullback_rets(seed)[:62] if seed == 0 else pullback_rets(seed)[5:62]
        rets += [-0.012, -0.012, -0.011, -0.01, -0.008, 0.014, 0.006, 0.004, 0.004]
    return mk(rets + list(extra))


def test_replay_trades_funds_only_and_labels_itself():
    bars = history()
    rep = rp.replay({"SPY": bars, "NVDA": bars}, fictional=True, symbols=("SPY", "NVDA"))
    assert rep["replay"]["symbols"] == ["SPY"]  # a single stock is left out: no historical earnings dates
    assert rep["fictional"] is True and rep["summary"]["total"] >= 1
    assert "not evidence" in rep["replay"]["note"]
    assert all(t["why_entered"]["stop"] < t["entry_price"] < t["why_entered"]["target"] for t in rep["trades"])


def test_replay_never_looks_ahead():
    bars = history()
    cut = len(bars) - 25
    early = rp.replay({"SPY": bars[:cut]}, True, ("SPY",))
    late = rp.replay({"SPY": bars}, True, ("SPY",))
    last_day = bars[cut - 1].day.isoformat()
    seen = lambda rep: sorted((t["why_entered"]["bar_day"], t["entry_price"]) for t in rep["trades"] if t["why_entered"]["bar_day"] <= last_day)  # noqa: E731
    assert seen(early) == seen(late) and seen(early)  # the first part of history behaves the same with or without the future


def test_replay_is_deterministic_and_changes_nothing_outside_itself():
    bars = history()
    a, b = rp.replay({"SPY": bars}, True, ("SPY",)), rp.replay({"SPY": bars}, True, ("SPY",))
    assert a["trades"] == b["trades"] and a["summary"] == b["summary"]


def test_replay_runs_on_demo_data_and_renders_text():
    p = DemoDataProvider()
    names = tuple(s for s in sw.SYMBOLS if s in {"SPY", "QQQ", "IWM"})
    rep = rp.replay(p.daily_bars(names, months=12), p.fictional, names)
    text = rp.render(rep)
    assert "FICTIONAL" in text and "buying and holding" in text and "not evidence" in text
    assert rep["replay"]["days"] > 100
