"""IBKR first, Yahoo only for research data IBKR lacks; never for order quotes (synthetic fixtures only)."""
from dataclasses import replace
from datetime import timedelta

import pytest

from helpers import NOW, make_quote
from optplat import optionlanes as ol
from optplat.fallback_data import FALLBACK_SOURCE, IBKRWithYahooFallback
from optplat.marketdata import ChainRow, MarketDataProvider, MarketSnapshot
from optplat.models import OptionContract, Right


def _row(strike=102.0):
    return ChainRow(OptionContract("AAA", NOW.date() + timedelta(days=40), Right.CALL, strike), 4.9, 5.1, 100, 500, 0.3)


def _snap(source, rows=(None,), verified=False):
    rows = tuple(_row() for _ in rows) if rows else ()
    return MarketSnapshot("AAA", 100.0, (100.0,) * 5, rows, NOW, source, verified)


class FakeIBKR(MarketDataProvider):
    name = "ibkr-shared-research-only"
    execution_veto = True

    def __init__(self, snap=None, fail=False, bars=None):
        self.snap, self.fail, self.bars, self.calls = snap, fail, bars or {}, []

    def snapshot(self, symbol):
        self.calls.append("snapshot")
        if self.fail:
            raise ConnectionError("service down")
        return self.snap

    def snapshot_window(self, symbol, min_dte, max_dte, max_expiries=4):
        return self.snapshot(symbol)

    def quotes_for(self, contracts):
        return []

    def execution_quote(self, contract):
        self.calls.append("execution_quote")
        return None

    def decision_quotes_for(self, contracts):
        self.calls.append("decision_quotes_for")
        return []

    def daily_bars(self, symbols, months=2):
        return {s: self.bars[s] for s in symbols if s in self.bars}

    def intraday_bars(self, symbol):
        if self.fail:
            raise ConnectionError("service down")
        return []

    def health(self):
        return {"state": "OK"}


class FakeYahoo(MarketDataProvider):
    name = "yahoo-unofficial"

    def __init__(self):
        self.calls = []

    def snapshot(self, symbol):
        self.calls.append("snapshot")
        return _snap(self.name)

    def snapshot_window(self, symbol, min_dte, max_dte, max_expiries=4):
        return self.snapshot(symbol)

    def quotes_for(self, contracts):
        self.calls.append("quotes_for")
        return [make_quote(verified=False)]

    def execution_quote(self, contract):
        raise AssertionError("Yahoo must never be asked for an order quote")

    def daily_bars(self, symbols, months=2):
        self.calls.append(("daily_bars", tuple(symbols)))
        return {s: ["yahoo-bar"] for s in symbols}

    def intraday_bars(self, symbol):
        self.calls.append("intraday_bars")
        return ["yahoo-bar"]


def _wrap(ibkr, yahoo=None):
    y = yahoo or FakeYahoo()
    return IBKRWithYahooFallback(ibkr, lambda: y, clock=lambda: NOW), y


def test_ibkr_chain_with_quotes_is_used_and_yahoo_is_not_touched():
    ib_snap = _snap("ibkr-shared-research-only")
    p, y = _wrap(FakeIBKR(ib_snap))
    assert p.snapshot("AAA") is ib_snap and y.calls == []
    assert p.health()["yahoo_fallback"]["counts"]["snapshot"] == 0


@pytest.mark.parametrize("ibkr", [FakeIBKR(fail=True), FakeIBKR(_snap("ibkr-shared-research-only", rows=()))])
def test_yahoo_fills_in_a_chain_only_when_ibkr_fails_or_is_empty_and_is_labelled(ibkr):
    p, y = _wrap(ibkr)
    got = p.snapshot_window("AAA", 7, 60)
    assert got.source == FALLBACK_SOURCE and got.timestamp_verified is False and got.rows
    assert p.fallback_counts["snapshot"] == 1 and p.last_fallback["symbol"] == "AAA"


def test_order_quotes_never_come_from_yahoo():
    ib = FakeIBKR(fail=True)
    p, y = _wrap(ib)
    c = _row().contract
    assert p.quotes_for([c]) == [] and p.execution_quote(c) is None and p.decision_quotes_for([c]) == []
    assert p.execution_veto is True
    assert "quotes_for" not in y.calls and ib.calls == ["execution_quote", "decision_quotes_for"]


def test_daily_bars_fall_back_per_symbol_only_for_names_ibkr_left_out():
    p, y = _wrap(FakeIBKR(bars={"AAA": ["ibkr-bar"]}))
    out = p.daily_bars(["AAA", "^VIX"])
    assert out == {"AAA": ["ibkr-bar"], "^VIX": ["yahoo-bar"]}
    assert y.calls == [("daily_bars", ("^VIX",))] and p.fallback_counts["daily_bars"] == 1


def test_intraday_bars_fall_back_when_ibkr_fails():
    p, _ = _wrap(FakeIBKR(fail=True))
    assert p.intraday_bars("AAA") == ["yahoo-bar"] and p.fallback_counts["intraday_bars"] == 1


def test_no_yahoo_installed_means_no_fallback_not_a_crash():
    def broken():
        raise ImportError("yfinance")
    p = IBKRWithYahooFallback(FakeIBKR(_snap("ibkr-shared-research-only", rows=())), broken)
    assert p.snapshot("AAA").source == "ibkr-shared-research-only"  # IBKR's empty answer, unchanged
    assert p.daily_bars(["^VIX"]) == {} and p.intraday_bars("AAA") == []
    assert p.health()["yahoo_fallback"]["available"] is False
    with pytest.raises(RuntimeError, match="fallback unavailable"):
        IBKRWithYahooFallback(FakeIBKR(fail=True), broken).snapshot("AAA")


def test_option_lanes_never_pick_a_contract_from_a_yahoo_fallback_chain():
    p = replace(ol.SWING_BASE, otm_pct=2.0)
    assert ol.pick_contract(_snap("yahoo-unofficial", verified=True), Right.CALL, NOW, p) is not None
    assert ol.pick_contract(_snap(FALLBACK_SOURCE), Right.CALL, NOW, p) is None


# ---- end to end: a Yahoo fallback chain can suggest a trade, but only a verified IBKR quote can fill it
from test_ibkr_verified_fills import C, UP  # noqa: E402
from optplat.broker import SimBroker  # noqa: E402
from optplat.engine import TradingEngine  # noqa: E402
from optplat.ibkr_data import VERIFIED_SOURCE  # noqa: E402
from optplat.marketdata import StaticDataProvider  # noqa: E402
from optplat.models import Quote  # noqa: E402
from optplat.orders import OrderManager  # noqa: E402
from optplat.store import Store  # noqa: E402
from optplat.strategy import LiquidTrendStrategy  # noqa: E402


class DownIBKR(MarketDataProvider):
    name = "ibkr-shared-research-only"
    execution_veto = True

    def __init__(self, verified):
        self.verified, self.asked = verified, []

    def snapshot(self, symbol):
        raise ConnectionError("service down")

    def quotes_for(self, contracts):
        return []

    def execution_quote(self, contract):
        self.asked.append(contract)
        return self.verified(contract)


def _engine(verified):
    yahoo = StaticDataProvider(lambda: NOW)
    yahoo.set_snapshot(MarketSnapshot("AAA", UP[-1], UP, (ChainRow(C, 4.90, 5.10, 200, 2000, 0.3),), NOW,
                                      "yahoo-unofficial", False))
    ibkr = DownIBKR(verified)
    broker = SimBroker()
    engine = TradingEngine(OrderManager(broker, Store(":memory:"), clock=lambda: NOW),
                           IBKRWithYahooFallback(ibkr, lambda: yahoo, clock=lambda: NOW), LiquidTrendStrategy(),
                           clock=lambda: NOW)
    engine.set_config({"watchlist": ["AAA"], "auto_entries": True})
    return engine, broker, ibkr


def test_ibkr_down_and_no_verified_quote_means_no_fill_on_yahoo_data():
    engine, broker, ibkr = _engine(lambda c: None)
    report = engine.run_cycle()
    assert report["entries"][0]["result"] == "RISK_REJECTED" and broker.get_positions() == []
    assert ibkr.asked == [C]


def test_a_yahoo_suggested_entry_fills_only_on_ibkrs_verified_quote():
    engine, broker, ibkr = _engine(lambda c: Quote(c, 4.90, 5.10, NOW, VERIFIED_SOURCE, timestamp_verified=True))
    report = engine.run_cycle()
    assert report["entries"][0]["result"] == "FILLED" and len(broker.get_positions()) == 1
    assert ibkr.asked == [C]


def test_earnings_dates_come_from_yahoo_on_ibkr_data_unless_the_fallback_is_off():
    from optplat.events import earnings_source_for, yahoo_earnings_dates
    assert earnings_source_for("ibkr") is yahoo_earnings_dates
    assert earnings_source_for("ibkr", "none") is None
    assert earnings_source_for("yahoo") is yahoo_earnings_dates
    assert earnings_source_for("demo") is None
