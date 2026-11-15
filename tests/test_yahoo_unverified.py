"""Challenge C5: Yahoo quote times are download times, never exchange times. Pin that, offline."""
import sys
import types
from datetime import timedelta

import pytest
from helpers import NOW

from optplat.marketdata import YahooDataProvider
from optplat.models import OptionContract, Right

EXPIRY = NOW.date() + timedelta(days=60)
CONTRACT = OptionContract("AAA", EXPIRY, Right.CALL, 100.0)


class _Frame:
    def __init__(self, records):
        self._r = records

    def to_dict(self, _orient):
        return list(self._r)



class _Series:
    def __init__(self, v):
        self._v = v

    def tolist(self):
        return list(self._v)


class _Chain:
    calls = _Frame([{"strike": 100, "bid": 1.0, "ask": 1.2, "volume": 10, "openInterest": 50}])
    puts = _Frame([])


class _Ticker:
    options = (EXPIRY.isoformat(),)

    def __init__(self, symbol):
        pass

    def history(self, **_kw):
        return {"Close": _Series([100.0 + i for i in range(30)])}

    def option_chain(self, _expiry):
        return _Chain()


@pytest.fixture
def fake_yfinance(monkeypatch):
    monkeypatch.setitem(sys.modules, "yfinance", types.SimpleNamespace(Ticker=_Ticker))


def test_yahoo_snapshot_and_quotes_are_never_verified(fake_yfinance):
    p = YahooDataProvider(clock=lambda: NOW)
    snap = p.snapshot("AAA")
    assert snap.rows and snap.timestamp_verified is False
    quotes = p.quotes_for([CONTRACT])
    assert quotes and all(q.timestamp_verified is False for q in quotes)
    assert all(q.as_of == NOW for q in quotes)  # download time, not exchange time


def test_default_policy_rejects_yahoo_quotes(fake_yfinance):
    from helpers import make_intent
    from optplat.models import Account
    from optplat.risk import RiskPolicy, evaluate

    policy = RiskPolicy()
    assert policy.require_verified_quote_time is True
    q = YahooDataProvider(clock=lambda: NOW).quotes_for([CONTRACT])[0]
    account = Account(equity=100_000, cash=100_000, open_premium=0)
    buy = evaluate(make_intent(contract=CONTRACT), q, account, [], policy, now=NOW)
    assert not buy.allowed
    assert "Quote time is not verified by the broker or venue" in buy.failures
