from datetime import date, datetime, timedelta, timezone

from fastapi.testclient import TestClient

from optplat import shadow
from optplat.marketdata import ChainRow, MarketSnapshot
from optplat.models import OptionContract, Right
from optplat.store import Store

D0 = date(2026, 11, 9)  # Monday
T0 = datetime(2026, 11, 9, 16, tzinfo=timezone.utc)
EXP = D0 + timedelta(days=40)


def row(strike=100.0, bid=2.0, ask=2.1, vol=500, right=Right.CALL, expiry=EXP):
    return ChainRow(OptionContract("AAA", expiry, right, strike), bid, ask, vol, 300, 0.3)


def snap(rows, spot=100.0, now=T0):
    return MarketSnapshot("AAA", spot, (98.0, 99.0, 100.0), tuple(rows), now, "t", True, True)


def occ(r):
    return r.contract.occ_symbol.strip()


def test_select_filters_and_ranks():
    good = row(100, vol=900)
    wide = row(105, bid=1.0, ask=2.0)  # 67% spread
    near = row(95, expiry=D0 + timedelta(days=3))
    far = row(90, expiry=D0 + timedelta(days=300))
    zero = row(110, bid=0.0, ask=0.1)
    crossed = row(115, bid=3.0, ask=2.0)
    quiet = row(120, vol=10)
    got = shadow.select(snap([quiet, wide, near, far, zero, crossed, good]), D0)
    assert [occ(r) for r in got] == [occ(good), occ(quiet)]


def test_select_caps_per_underlying():
    rows = [row(50 + i, vol=i) for i in range(20)]
    assert len(shadow.select(snap(rows), D0)) == shadow.PER_UNDERLYING


def test_follow_records_features_once_per_day_and_marks_missing_ones():
    s = Store(":memory:")
    r = row()
    assert shadow.observe(s, snap([r]), D0, T0, True) == {"followed": 1, "points": 0}
    assert shadow.observe(s, snap([r]), D0, T0 + timedelta(hours=1), True)["followed"] == 0  # same contract, same day
    f = s.shadow_all_follows(True)[0]
    assert f["entry_ask"] == 2.1 and f["entry_bid"] == 2.0 and f["dte"] == 40 and f["symbol"] == "AAA"
    assert f["missing_features"] == ["iv_percentile", "days_to_earnings"]
    assert "iv_percentile" not in f and "days_to_earnings" not in f
    assert s.shadow_all_follows(False) == []  # fictional and real data stay apart


def test_same_scan_adds_no_point_but_later_scans_do():
    s = Store(":memory:")
    r = row()
    shadow.observe(s, snap([r]), D0, T0, True)
    assert shadow.observe(s, snap([r]), D0, T0, True)["points"] == 0  # the scan that followed it
    out = shadow.observe(s, snap([row(bid=2.5, ask=2.6)], now=T0), D0 + timedelta(days=1), T0 + timedelta(days=1), True)
    assert out["points"] == 1
    pt = s.shadow_all_points(True)[0]
    assert pt["bid"] == 2.5 and pt["age"] == 1 and pt["followed_day"] == D0.isoformat()


def test_point_cadence_dense_then_daily():
    d = D0
    assert shadow.point_due(3, {d.isoformat()}, d)               # dense: a second point the same day
    assert not shadow.point_due(15, {d.isoformat()}, d)          # sparse: one per day
    assert shadow.point_due(15, set(), d)
    assert not shadow.point_due(shadow.MAX_AGE + shadow.SLACK + 1, set(), d)
    assert not shadow.point_due(-1, set(), d)


def test_contract_missing_from_chain_leaves_a_gap_not_a_guess():
    s = Store(":memory:")
    shadow.observe(s, snap([row()]), D0, T0, True)
    other = row(strike=130, vol=1)
    out = shadow.observe(s, snap([other]), D0 + timedelta(days=1), T0 + timedelta(days=1), True)
    assert out["points"] == 0
    assert all(p["contract"] != occ(row()) for p in s.shadow_all_points(True))


def test_report_counts_and_never_claims_gate_passed():
    s = Store(":memory:")
    assert shadow.report(s, True, D0)["complete_pct"] is None
    shadow.observe(s, snap([row()]), D0, T0, True)
    rep = shadow.report(s, True, D0)
    assert rep["followed"] == 1 and rep["underlyings"] == 1 and rep["trading_days"] == 1 and rep["complete_pct"] == 0.0
    assert rep["gate_met"]["followed"] is False and rep["gate_met_except_export"] is False


def test_report_marks_complete_when_path_reaches_30_days():
    s = Store(":memory:")
    shadow.observe(s, snap([row()]), D0, T0, True)
    later = D0 + timedelta(days=42)  # 30 trading days after Nov 9 (two holidays inside) is within the slack
    age = shadow.trading_days_between(D0, later)
    s.record_shadow_point(occ(row()), D0.isoformat(), True, T0.isoformat() + "x", later.isoformat(), {"age": max(age, shadow.MAX_AGE), "bid": 1.0})
    assert shadow.report(s, True, later)["complete_pct"] == 100.0


def test_api_endpoint_and_export_allow_list():
    from optplat.api import create_app
    from optplat.broker import SimBroker
    from optplat.engine import EngineConfig, TradingEngine
    from optplat.export import TABLES
    from optplat.marketdata import DemoDataProvider
    from optplat.orders import OrderManager
    from optplat.strategy import LiquidTrendStrategy

    assert "shadow_follows" in TABLES and "shadow_points" in TABLES
    manager = OrderManager(SimBroker(), Store(":memory:"))
    engine = TradingEngine(manager, DemoDataProvider(), LiquidTrendStrategy(), default_config=EngineConfig())
    with TestClient(create_app(manager, "t" * 24, engine, None)) as c:
        assert c.get("/api/shadow").status_code == 401
        body = c.get("/api/shadow", headers={"X-API-Token": "t" * 24}).json()
    assert body["followed"] == 0 and body["gate_met_except_export"] is False and body["fictional"] is True


def test_one_per_underlying_day_keeps_most_active_and_is_deterministic():
    f = lambda sym, day, c, vol: {"symbol": sym, "followed_day": day, "contract": c, "volume": vol}
    follows = [f("AAA", "2026-11-09", "AAA2", 100), f("AAA", "2026-11-09", "AAA1", 900), f("AAA", "2026-11-09", "AAA0", 900),
               f("AAA", "2026-11-10", "AAA3", None), f("BBB", "2026-11-09", "BBB1", 5), {"symbol": "", "followed_day": "2026-11-09"}]
    got = shadow.one_per_underlying_day(follows)
    assert [(g["symbol"], g["followed_day"], g["contract"]) for g in got] == [
        ("AAA", "2026-11-09", "AAA0"), ("AAA", "2026-11-10", "AAA3"), ("BBB", "2026-11-09", "BBB1")]
    assert shadow.one_per_underlying_day(list(reversed(follows))) == got


def test_report_counts_independent_observations_below_followed():
    s = Store(":memory:")
    shadow.observe(s, snap([row(100, vol=900), row(101, vol=800), row(102, vol=700)]), D0, T0, True)
    rep = shadow.report(s, True, D0)
    assert rep["followed"] == 3 and rep["independent_observations"] == 1


def _iv_row(strike, iv):
    return ChainRow(OptionContract("AAA", EXP, Right.CALL, strike), 2.0, 2.1, 500, 300, iv)


def test_name_iv_is_median_of_near_money_and_needs_three():
    near = [_iv_row(98, 0.2), _iv_row(100, 0.3), _iv_row(102, 0.5)]
    assert shadow.name_iv(snap(near + [_iv_row(130, 0.9)]), D0) == 0.3  # far strike ignored
    assert shadow.name_iv(snap(near[:2]), D0) is None
    assert shadow.name_iv(snap([_iv_row(100, 0.0)] * 3), D0) is None  # no usable IV is unknown, not zero


def test_iv_percentile_unknown_until_history_then_share_below():
    assert shadow.iv_percentile(0.3, {f"d{i}": 0.2 for i in range(shadow.MIN_IV_HISTORY - 1)}) is None
    hist = {f"d{i}": 0.1 + i / 100 for i in range(20)}
    assert shadow.iv_percentile(0.15, hist) == 25.0 and shadow.iv_percentile(None, hist) is None


def test_follow_gets_iv_percentile_after_enough_prior_days_and_uses_past_days_only():
    s = Store(":memory:")
    rows = [_iv_row(98, 0.3), _iv_row(100, 0.3), _iv_row(102, 0.3)]
    day, now = D0, T0
    for i in range(shadow.MIN_IV_HISTORY + 1):
        day, now = D0 + timedelta(days=i), T0 + timedelta(days=i)
        shadow.observe(s, snap(rows, now=now), day, now, True)
    last = [f for f in s.shadow_all_follows(True) if f["followed_day"] == day.isoformat()]
    first = [f for f in s.shadow_all_follows(True) if f["followed_day"] == D0.isoformat()]
    assert first and "iv_percentile" not in first[0] and "iv_percentile" in first[0]["missing_features"]
    assert last and last[0]["iv_percentile"] == 0.0 and "iv_percentile" not in last[0]["missing_features"]
    assert last[0]["name_iv"] == 0.3


class _Strat:
    def __init__(self, name, picks, boom=False):
        self.name, self.version, self._picks, self._boom = name, "1", picks, boom

    def propose(self, snapshot, now):
        from optplat.strategy import Proposal
        if self._boom:
            raise RuntimeError("bad")
        return [Proposal(r.contract, r.ask, 10.0 - i, {}) for i, r in enumerate(self._picks)]


def test_strategy_picks_are_followed_and_tagged(tmp_path):
    store = Store(tmp_path / "s.db")
    generic = [row(100 + i, vol=900 - i) for i in range(6)]
    odd = row(150, bid=1.0, ask=1.1, vol=1)  # not in the generic top six, only a strategy picks it
    s = snap(generic + [odd])
    a = _Strat("alpha", [odd, generic[0]])
    out = shadow.observe(store, s, D0, T0, False, [a, _Strat("broken", [], boom=True)])
    assert out["followed"] == 7
    by = {f["contract"]: f for f in store.shadow_all_follows(False)}
    assert by[occ(odd)]["chosen_by"] == [{"strategy": "alpha", "version": "1", "rank": 1, "score": 10.0}]
    assert by[occ(generic[0])]["chosen_by"][0]["rank"] == 2  # a generic follow also gets the tag
    assert "chosen_by" not in by[occ(generic[1])]
    shadow.observe(store, s, D0, T0, False, [a])  # a second scan the same day adds nothing and never duplicates a tag
    assert len(store.shadow_all_follows(False)) == 7
    assert len({f["contract"]: f for f in store.shadow_all_follows(False)}[occ(odd)]["chosen_by"]) == 1


def test_strategy_picks_outside_chain_are_skipped(tmp_path):
    store = Store(tmp_path / "s.db")
    ghost = row(500)
    s = snap([row(100)])
    out = shadow.observe(store, s, D0, T0, False, [_Strat("alpha", [ghost])])
    assert out["followed"] == 1 and not any("chosen_by" in f for f in store.shadow_all_follows(False))
