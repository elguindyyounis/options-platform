from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from helpers import NOW
from optplat.api import create_app
from optplat.broker import SimBroker
from optplat.engine import EngineConfig, TradingEngine
from optplat.marketdata import Bar, ChainRow, DemoDataProvider, StaticDataProvider
from optplat.models import OptionContract, Right
from optplat.orders import OrderManager
from optplat.scanner import (MIN_UNUSUAL_VOLUME, UNIVERSE, Scanner, completed_bars, rank_active, unusual_contracts)
from optplat.store import Store
from optplat.strategy import LiquidTrendStrategy
from test_engine import EXPIRY, snapshot

TODAY = NOW.date()  # a Monday, 10:00 New York time: the regular session is open


def bars(vol_last=2_000_000, base=1_000_000, n=25, close=100.0, today_volume=None):
    days = [TODAY - timedelta(days=n - i) for i in range(n)]
    out = [Bar(d, close, base) for d in days[:-1]] + [Bar(days[-1], close * 1.02, vol_last)]
    if today_volume is not None:
        out.append(Bar(TODAY, close, today_volume))
    return out


# ------------------------------------------------------------ ranking
def test_names_are_ranked_by_dollar_volume_with_relative_volume_and_a_surge_flag():
    raw = {"BIG": bars(vol_last=5_000_000, close=200.0), "SURGE": bars(vol_last=3_000_000, base=1_000_000), "QUIET": bars(vol_last=900_000)}
    rows = rank_active(raw, NOW)
    assert [r["symbol"] for r in rows] == ["BIG", "SURGE", "QUIET"] and [r["rank"] for r in rows] == [1, 2, 3]
    big = rows[0]
    assert big["dollar_volume"] == round(204.0 * 5_000_000) and big["relative_volume"] == 5.0 and big["surge"]
    assert not rows[2]["surge"] and rows[2]["change_pct"] == 2.0


def test_todays_partial_bar_is_dropped_while_the_session_is_open():
    raw = bars(today_volume=10)  # a tiny partial volume must not make the name look dead
    assert completed_bars(raw, NOW)[-1].day != TODAY
    assert rank_active({"X": raw}, NOW)[0]["volume"] == 2_000_000
    closed = NOW.replace(hour=22)  # after the close the day is complete
    assert completed_bars(raw, closed)[-1].day == TODAY


def test_too_little_or_bad_history_is_skipped_not_guessed():
    short = bars(n=10)
    bad = bars()
    bad[-3] = Bar(bad[-3].day, float("nan"), 5)
    rows = rank_active({"SHORT": short, "BAD": bad, "OK": bars()}, NOW)
    assert [r["symbol"] for r in rows] == ["BAD", "OK"] or [r["symbol"] for r in rows] == ["OK", "BAD"]
    assert "SHORT" not in [r["symbol"] for r in rows]
    assert rank_active({"BAD": [Bar(TODAY - timedelta(days=i), -1.0, 5) for i in range(30)]}, NOW) == []


# ------------------------------------------------------------ unusual activity
def snap_with(*rows):
    return snapshot().__class__(**{**snapshot().__dict__, "rows": tuple(rows)})


def row(volume, oi, bid=4.9, ask=5.1, strike=160.0, right=Right.CALL, days=60):
    return ChainRow(OptionContract("AAA", TODAY + timedelta(days=days), right, strike), bid, ask, volume, oi, 0.3)


def flagged(*rows):
    return unusual_contracts(snap_with(*rows), NOW)


def test_thresholds_volume_ratio_and_zero_open_interest():
    assert flagged(row(MIN_UNUSUAL_VOLUME - 1, 10)) == []
    hit = flagged(row(150, 40))
    assert len(hit) == 1 and hit[0]["volume_oi_ratio"] == 3.75
    assert flagged(row(150, 52)) == []  # 2.88x: ordinary turnover
    zero = flagged(row(500, 0))
    assert len(zero) == 1 and zero[0]["volume_oi_ratio"] is None and zero[0]["oi_state"] == "REPORTED_ZERO"
    assert flagged(row(499, 0)) == [] and flagged(row(499, None)) == []
    assert flagged(row(500, None))[0]["oi_state"] == "MISSING"


def test_crossed_or_zero_ask_quotes_are_never_flagged_and_ratio_is_never_infinite():
    assert flagged(row(900, 10, bid=5.2, ask=5.0)) == [] and flagged(row(900, 10, bid=0.0, ask=0.0)) == []
    for r in flagged(row(900, 0), row(900, None), row(900, 100)):
        assert r["volume_oi_ratio"] is None or r["volume_oi_ratio"] < 1e6


def test_wide_or_thin_or_short_dated_contracts_are_observe_only():
    good = flagged(row(2000, 500, bid=4.95, ask=5.05))[0]
    assert good["decision"] == "REVIEWABLE" and good["liquidity_tier"] in ("A", "B")
    wide = flagged(row(2000, 500, bid=3.0, ask=5.0))[0]
    assert wide["decision"] == "OBSERVE_ONLY" and wide["why_observe_only"] == "wide or thin market"
    near = flagged(row(2000, 500, bid=4.95, ask=5.05, days=3))[0]
    assert near["decision"] == "OBSERVE_ONLY" and "expiry" in near["why_observe_only"]
    assert good["quoted_turnover_usd"] == round(5.05 * 2000 * 100)
    thin = flagged(row(1000, 200, bid=4.95, ask=5.05))[0]  # open interest 200 is thin by the liquidity tiers
    assert thin["decision"] == "OBSERVE_ONLY"


# ------------------------------------------------------------ the scan job
def make(provider=None, **kw):
    store = Store(":memory:")
    prov = provider or DemoDataProvider(clock=lambda: NOW)
    return Scanner(prov, store, clock=lambda: NOW, **kw), store


def test_a_demo_scan_ranks_names_reads_chains_and_is_labelled_fictional():
    sc, store = make()
    out = sc.run()
    assert out["fictional"] is True and out["source"] == "demo-synthetic"
    assert 0 < len(out["active_names"]) <= 25 and out["coverage"]["chains_scanned"] > 0
    assert out["active_names"][0]["dollar_volume"] >= out["active_names"][-1]["dollar_volume"]
    assert out["option_names"] == sorted(out["option_names"], key=lambda r: -r["total_volume"])
    assert out["limitations"] and "thresholds" in out
    assert store.latest_scan(True)["as_of"] == NOW.isoformat() and store.latest_scan(False) is None  # kept apart


def test_a_provider_without_bars_says_so_and_ranks_nothing():
    sc, store = make(StaticDataProvider(lambda: NOW))
    out = sc.run()
    assert out["active_names"] == [] and any("daily bars unavailable" in e for e in out["errors"])
    assert store.latest_scan(False)["errors"]


def test_a_time_budget_stops_chain_reads_but_keeps_the_ranking():
    sc, _ = make(budget_s=-1.0)
    out = sc.run()
    assert out["active_names"] and any("time budget" in e for e in out["errors"]) and out["coverage"]["chains_scanned"] == 0


def test_a_chain_that_fails_or_is_rejected_is_reported_not_hidden():
    class Flaky(DemoDataProvider):
        def snapshot_window(self, symbol, *args, **kw):
            raise RuntimeError("rate limited")

    sc, _ = make(Flaky(clock=lambda: NOW))
    out = sc.run()
    assert out["coverage"]["chains_failed"] > 0 and any("chain unavailable" in e for e in out["errors"])


def test_the_universe_is_a_fixed_list_without_duplicates():
    assert len(UNIVERSE) == len(set(UNIVERSE)) and "SPY" in UNIVERSE and len(UNIVERSE) > 50


# ------------------------------------------------------------ engine and API
def build_engine():
    manager = OrderManager(SimBroker(), Store(":memory:"))
    engine = TradingEngine(manager, DemoDataProvider(), LiquidTrendStrategy(), default_config=EngineConfig())
    return manager, engine


def test_scan_interval_is_validated_and_off_by_default():
    _, engine = build_engine()
    assert engine.config().scan_interval_s == 0
    for bad in (1, 599, 90_000):
        with pytest.raises(ValueError, match="scan_interval_s"):
            engine.set_config({"scan_interval_s": bad})
    assert engine.set_config({"scan_interval_s": 600}).scan_interval_s == 600


def test_maybe_scan_respects_the_interval():
    _, engine = build_engine()
    engine.maybe_scan()
    assert engine.scanner.latest() is None and not engine.scanner.running()  # off
    engine.set_config({"scan_interval_s": 600})
    engine.maybe_scan()
    engine.scanner._thread.join(timeout=30)
    first = engine.scanner.latest()
    assert first is not None
    engine.maybe_scan()  # due again only after the interval
    assert not engine.scanner.running()


def test_scan_endpoints_need_the_token_and_return_the_latest_result():
    manager, engine = build_engine()
    tok = "t" * 24
    with TestClient(create_app(manager, tok, engine)) as c:
        assert c.get("/api/scan").status_code == 401 and c.post("/api/scan/run").status_code == 401
        h = {"X-API-Token": tok}
        assert c.get("/api/scan", headers=h).json()["result"] is None
        assert c.post("/api/scan/run", headers=h).json()["started"] is True
        engine.scanner._thread.join(timeout=30)
        body = c.get("/api/scan", headers=h).json()
        assert body["result"]["active_names"] and body["status"]["running"] is False
        assert c.put("/api/engine/config", json={"scan_interval_s": 1200}, headers=h).json()["scan_interval_s"] == 1200


# ------------------------------------------------------------ scanner v2: low open interest, buy or sell, does it stick
from dataclasses import replace  # noqa: E402
from datetime import datetime, timezone  # noqa: E402

from optplat.scanner import (LOW_OI, MIN_LOW_OI_VOLUME, compare_with_prior, heat_map, sentiment, session_day, sessions_in_oi_change, trade_side)  # noqa: E402
from optplat.universe import SECTOR_OF, SECTORS  # noqa: E402


def test_very_low_open_interest_is_flagged_at_a_lower_volume_but_zero_or_missing_is_not():
    hit = flagged(row(MIN_LOW_OI_VOLUME, 5))
    assert len(hit) == 1 and hit[0]["low_oi"] is True and hit[0]["volume_oi_ratio"] == 20.0
    assert flagged(row(MIN_LOW_OI_VOLUME - 1, 5)) == []          # still needs real volume
    assert flagged(row(MIN_LOW_OI_VOLUME, LOW_OI)) == []         # OI of 10 is not "low": the normal 150 bar applies
    assert flagged(row(150, LOW_OI))[0]["low_oi"] is False
    assert flagged(row(MIN_LOW_OI_VOLUME, 0)) == [] and flagged(row(MIN_LOW_OI_VOLUME, None)) == []  # zero or missing: 500 needed
    assert flagged(row(500, 0))[0]["low_oi"] is True and flagged(row(500, None))[0]["low_oi"] is False
    plain = flagged(row(150, 40))[0]
    assert hit[0]["score"] > plain["score"] - 5 and flagged(row(150, 5))[0]["score"] >= flagged(row(150, 40))[0]["score"]


def test_low_open_interest_is_never_called_reviewable_just_because_the_ratio_is_big():
    assert flagged(row(400, 5, bid=4.95, ask=5.05))[0]["decision"] == "OBSERVE_ONLY"  # the engine's own liquidity bar would refuse it


@pytest.mark.parametrize("last,bid,ask,expected", [
    (5.10, 4.90, 5.10, ("AT_ASK", "BUY")), (5.12, 4.90, 5.10, ("ABOVE_ASK", "BUY")),
    (4.90, 4.90, 5.10, ("AT_BID", "SELL")), (4.88, 4.90, 5.10, ("BELOW_BID", "SELL")),
    (5.00, 4.90, 5.10, ("MID", "UNCLEAR")), (5.07, 4.90, 5.10, ("AT_ASK", "BUY")), (4.93, 4.90, 5.10, ("AT_BID", "SELL")),
    (None, 4.90, 5.10, ("UNKNOWN", "UNCLEAR")), (0.0, 4.90, 5.10, ("UNKNOWN", "UNCLEAR")),
    (9.00, 4.90, 5.10, ("UNKNOWN", "UNCLEAR")), (1.00, 4.90, 5.10, ("UNKNOWN", "UNCLEAR")),   # far outside the quote: stale
    (5.0, 5.2, 5.0, ("UNKNOWN", "UNCLEAR")),                                                  # crossed quote
])
def test_buy_or_sell_is_guessed_from_where_the_last_trade_printed(last, bid, ask, expected):
    assert trade_side(last, bid, ask) == expected


def test_a_flagged_row_carries_the_print_and_the_guess():
    r = unusual_contracts(snap_with(ChainRow(OptionContract("AAA", TODAY + timedelta(days=60), Right.CALL, 160.0), 4.9, 5.1, 900, 100, 0.3, 5.1)), NOW)[0]
    assert r["print"] == "AT_ASK" and r["likely_side"] == "BUY" and r["last"] == 5.1
    assert flagged(row(900, 100))[0]["likely_side"] == "UNCLEAR"   # no last price in the feed: no guess


def prior_sighting(side="BUY", right="C", volume=800, oi=40):
    return {"day": "2026-11-09", "symbol": "AAA", "contract": "AAA", "right": right, "volume": volume, "open_interest": oi, "likely_side": side}


@pytest.mark.parametrize("side,right,oi_before,oi_now,position,lean", [
    ("BUY", "C", 40, 540, "BUY_TO_OPEN", "BULLISH"), ("BUY", "P", 40, 540, "BUY_TO_OPEN", "BEARISH"),
    ("SELL", "C", 40, 540, "SELL_TO_OPEN", "BEARISH"), ("SELL", "P", 40, 540, "SELL_TO_OPEN", "BULLISH"),
    ("BUY", "C", 2000, 1100, "BUY_TO_CLOSE", "UNCLEAR"), ("SELL", "P", 2000, 1100, "SELL_TO_CLOSE", "UNCLEAR"),
    ("BUY", "C", 40, 150, "UNCLEAR", "UNCLEAR"), ("UNCLEAR", "C", 40, 540, "UNCLEAR", "UNCLEAR"),
])
def test_next_day_open_interest_decides_open_versus_close(side, right, oi_before, oi_now, position, lean):
    out = compare_with_prior(prior_sighting(side, right, oi=oi_before), oi_now, date(2026, 11, 10))
    assert out["position_read"] == position and out["lean"] == lean
    assert out["oi_change"] == oi_now - oi_before


def test_open_interest_comparison_refuses_to_guess_without_the_numbers_or_across_a_long_gap():
    d = date(2026, 11, 10)
    assert compare_with_prior(prior_sighting(), None, d)["oi_verdict"] == "UNKNOWN"
    assert compare_with_prior(prior_sighting(oi=None), 500, d)["oi_verdict"] == "UNKNOWN"
    far = compare_with_prior(prior_sighting(), 540, date(2026, 11, 16))
    assert far["oi_verdict"] == "TOO_FAR_APART" and far["position_read"] == "UNCLEAR" and far["oi_change"] is None
    assert compare_with_prior(prior_sighting(), 540, date(2026, 11, 13))["oi_verdict"] == "OI_ROSE"  # a long weekend is still fine


def ny(y, m, d, h, mi=0):
    from zoneinfo import ZoneInfo
    return datetime(y, m, d, h, mi, tzinfo=ZoneInfo("America/New_York"))


def test_the_session_day_skips_weekends_holidays_and_the_hours_before_the_open():
    assert session_day(ny(2026, 11, 12, 11)) == date(2026, 11, 12)
    assert session_day(ny(2026, 11, 12, 20)) == date(2026, 11, 12)    # after the close: still that day's volume
    assert session_day(ny(2026, 11, 12, 8)) == date(2026, 11, 11)     # before the open: yesterday's figures
    assert session_day(ny(2026, 11, 14, 12)) == date(2026, 11, 13)    # Saturday
    assert session_day(ny(2026, 11, 16, 8)) == date(2026, 11, 13)     # Monday before the open
    assert session_day(ny(2026, 11, 26, 12)) == date(2026, 11, 25)    # Thanksgiving


def test_unusual_history_keeps_the_biggest_sighting_per_day_and_keeps_real_and_fictional_apart():
    st = Store(":memory:")
    st.record_unusual("2026-11-09", True, [{"contract": "X1", "symbol": "X", "volume": 300}])
    st.record_unusual("2026-11-09", True, [{"contract": "X1", "symbol": "X", "volume": 200}])   # a smaller later reading
    st.record_unusual("2026-11-09", True, [{"contract": "X1", "symbol": "X", "volume": 900}])
    st.record_unusual("2026-11-10", True, [{"contract": "X1", "symbol": "X", "volume": 50}])
    st.record_unusual("2026-11-09", False, [{"contract": "X1", "symbol": "X", "volume": 1}])
    before = st.unusual_before("2026-11-10", True)
    assert before["X1"]["volume"] == 900 and before["X1"]["day"] == "2026-11-09"   # today is never "before"
    assert st.unusual_before("2026-11-09", True) == {}
    assert st.unusual_before("2026-11-10", False)["X1"]["volume"] == 1
    assert st.unusual_streak("2026-11-11", True, "X1") == 2 and st.unusual_streak("2026-11-11", True, "none") == 0


class OneContract(DemoDataProvider):
    """Demo chains plus one fixed SPY call whose volume, open interest and last trade the test sets for each day."""
    def __init__(self, clock, **kw):
        super().__init__(clock=clock)
        self.set(**kw)

    def set(self, volume, oi, last=5.1):
        self.contract = (volume, oi, last)

    def snapshot_window(self, symbol, *args, **kw):
        snap = super().snapshot_window(symbol, *args, **kw)
        if symbol != "SPY":
            return snap
        volume, oi, last = self.contract
        c = OptionContract("SPY", TODAY + timedelta(days=60), Right.CALL, 7777.0)  # a fixed contract, whatever day it is
        return replace(snap, rows=snap.rows + (ChainRow(c, 4.9, 5.1, volume, oi, 0.2, last),))


def test_a_contract_that_was_unusual_yesterday_is_followed_up_and_open_interest_decides_open_or_close():
    clock = {"now": NOW}
    prov = OneContract(lambda: clock["now"], volume=800, oi=40)
    st = Store(":memory:")
    sc = Scanner(prov, st, clock=lambda: clock["now"], universe=("SPY", "AAPL", "MSFT"))
    day1 = sc.run()
    mine = next(u for u in day1["unusual"] if u["strike"] == 7777.0)
    assert mine["sightings"] == 1 and mine["likely_side"] == "BUY" and day1["follow_ups"] == []
    clock["now"] = NOW + timedelta(days=1)
    prov.set(volume=90, oi=560, last=5.0)           # open interest rose by 520, 65% of yesterday's 800 contracts
    day2 = sc.run()
    fu = next(f for f in day2["follow_ups"] if f["strike"] == 7777.0)
    assert fu["oi_verdict"] == "OI_ROSE" and fu["position_read"] == "BUY_TO_OPEN" and fu["lean"] == "BULLISH"
    assert fu["prior_day"] == day1["session_day"] and fu["oi_change"] == 520 and fu["symbol"] == "SPY"
    assert day2["coverage"]["follow_up_names"] >= 1
    # the same contract unusual again keeps its history on the row itself
    clock["now"] = NOW + timedelta(days=2)
    prov.set(volume=2000, oi=100, last=5.1)         # ratio 20: unusual a second time, and open interest fell back
    day3 = sc.run()
    again = next(u for u in day3["unusual"] if u["strike"] == 7777.0)
    assert again["sightings"] == 2 and again["history"]["prior_volume"] == 800   # the day it was last unusual, not yesterday's quiet reading
    assert again["history"]["oi_verdict"] == "OI_FLAT_OR_MIXED"


def test_a_weekend_rescan_of_fridays_figures_is_not_a_second_day():
    fri = ny(2026, 11, 13, 12).astimezone(timezone.utc)
    sat = ny(2026, 11, 14, 12).astimezone(timezone.utc)
    clock = {"now": fri}
    prov = OneContract(lambda: clock["now"], volume=800, oi=40)
    st = Store(":memory:")
    sc = Scanner(prov, st, clock=lambda: clock["now"], universe=("SPY", "AAPL", "MSFT"))
    first = sc.run()
    clock["now"] = sat
    second = sc.run()
    assert first["session_day"] == second["session_day"] == "2026-11-13"
    assert second["follow_ups"] == []
    assert all(u["sightings"] == 1 for u in second["unusual"])


def test_the_sector_map_covers_every_name_once_and_the_universe_is_bigger_and_mixed_cap():
    assert len(UNIVERSE) >= 150 and len(UNIVERSE) == len(set(UNIVERSE))
    flat = [s for names in SECTORS.values() for s in names]
    assert len(flat) == len(set(flat)) and set(flat) == set(UNIVERSE) and all(SECTOR_OF[s] for s in UNIVERSE)
    assert {"AAPL", "NVDA", "HOOD", "DKNG", "CRSP", "SOFI"} <= set(UNIVERSE)   # mega down to mid-cap


def ranked_row(sym, change, rel=1.0, usd=1e9, surge=False):
    return {"symbol": sym, "change_pct": change, "relative_volume": rel, "dollar_volume": usd, "surge": surge}


def test_heat_map_averages_each_sector_and_names_its_movers():
    h = heat_map([ranked_row("AAPL", 2.0), ranked_row("MSFT", -1.0), ranked_row("NVDA", 3.0, surge=True), ranked_row("JPM", -2.0)])
    secs = {s["sector"]: s for s in h["sectors"]}
    assert secs["Mega-cap tech"]["avg_change_pct"] == 1.33 and secs["Mega-cap tech"]["advancers"] == 2 and secs["Mega-cap tech"]["decliners"] == 1
    assert secs["Mega-cap tech"]["surging"] == 1 and secs["Mega-cap tech"]["leaders"][0]["symbol"] == "NVDA"
    assert h["sectors"][0]["sector"] == "Mega-cap tech" and len(h["names"]) == 4 and h["names"][0]["sector"] == "Mega-cap tech"


def flow(symbol_right, side, usd=100_000):
    return {"right": symbol_right, "likely_side": side, "quoted_turnover_usd": usd}


def test_sentiment_reads_breadth_and_labels_flow_only_from_known_sides():
    up = [ranked_row(f"S{i}", 1.0) for i in range(7)] + [ranked_row("D", -1.0)] * 3
    assert sentiment(up, [], [])["tone"] == "BROAD_STRENGTH" and sentiment(up, [], [])["breadth_pct"] == 70.0
    assert sentiment([ranked_row("A", -1)] * 8 + [ranked_row("B", 1)] * 2, [], [])["tone"] == "BROAD_WEAKNESS"
    assert sentiment([ranked_row("A", -1)] * 5 + [ranked_row("B", 1)] * 5, [], [])["tone"] == "MIXED"
    assert sentiment([], [], [])["tone"] == "UNKNOWN"
    bullish = sentiment(up, [], [flow("C", "BUY"), flow("P", "SELL"), flow("C", "BUY")])
    assert bullish["flow_lean"] == "BULLISH_LEAN" and bullish["bullish_flow_usd"] == 300_000 and bullish["bearish_flow_usd"] == 0
    bearish = sentiment(up, [], [flow("P", "BUY"), flow("C", "SELL"), flow("P", "BUY")])
    assert bearish["flow_lean"] == "BEARISH_LEAN"
    assert sentiment(up, [], [flow("C", "BUY"), flow("P", "BUY")])["flow_lean"] == "BALANCED"
    mostly_unknown = sentiment(up, [], [flow("C", "BUY", 10_000)] + [flow("C", "UNCLEAR", 500_000)])
    assert mostly_unknown["flow_lean"] == "UNCLEAR"          # a label from a sliver of known sides would mislead
    assert "inference" in bullish["basis"]


def test_a_demo_scan_has_a_heat_map_sentiment_and_low_open_interest_cases():
    sc, _ = make()
    out = sc.run()
    assert out["heat_map"]["sectors"] and out["sentiment"]["tone"] in ("BROAD_STRENGTH", "BROAD_WEAKNESS", "MIXED")
    assert any(u["low_oi"] for u in out["unusual"]) and {u["print"] for u in out["unusual"]} & {"AT_ASK", "AT_BID", "MID"}
    assert out["coverage"]["chains_planned"] >= 30 and out["fictional"] is True


@pytest.mark.parametrize("prior_day,day,expected", [
    (date(2026, 11, 9), date(2026, 11, 10), 1),    # next session: only the sighting day's trades
    (date(2026, 11, 13), date(2026, 11, 16), 1),   # Friday sighting, Monday read: a weekend adds no session
    (date(2026, 11, 9), date(2026, 11, 13), 4),    # Monday to Friday: four sessions are mixed into one change
    (date(2026, 11, 25), date(2026, 11, 27), 1),   # Thanksgiving (26th) is not a session
    (date(2026, 11, 10), date(2026, 11, 10), None), (date(2026, 11, 10), date(2026, 11, 9), None),
    (date(2026, 12, 30), date(2027, 1, 4), None),  # no 2027 calendar: unknown, never "clean"
])
def test_counts_the_sessions_an_open_interest_change_spans(prior_day, day, expected):
    assert sessions_in_oi_change(prior_day, day) == expected


def test_only_a_single_session_window_is_called_clean_and_the_read_itself_is_unchanged():
    one = compare_with_prior(prior_sighting(), 540, date(2026, 11, 10))
    assert one["oi_sessions"] == 1 and one["oi_window_clean"] is True and one["position_read"] == "BUY_TO_OPEN"
    four = compare_with_prior(prior_sighting(), 540, date(2026, 11, 13))
    assert four["oi_sessions"] == 4 and four["oi_window_clean"] is False
    assert four["position_read"] == "BUY_TO_OPEN" and four["lean"] == "BULLISH"   # display-only: the label itself did not change
    assert compare_with_prior(prior_sighting(), None, date(2026, 11, 10))["oi_window_clean"] is False   # no numbers: not clean
