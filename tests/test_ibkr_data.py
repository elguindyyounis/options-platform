"""Synthetic protocol fixtures only; no live connection or performance claim."""
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

import pytest

from helpers import NOW, CONTRACT, make_intent, make_quote
from optplat.ibkr_data import IBKRDataProvider, NoRedirect
from optplat.marketdata import ChainRow, MarketSnapshot, snapshot_to_dict, snapshot_from_dict
from optplat.models import Account, Position, Right, Side
from optplat.optionlanes import SWING_BASE, pick_contract
from optplat.risk import RiskPolicy, evaluate


def response(status='LIVE_UNVERIFIED'):
    return {'underlying':600., 'as_of':NOW.isoformat(),
            'bars':[{'timestamp':'2026-11-13','close':599.,'volume':1000.}],
            'rows':[{'expiry':CONTRACT.expiry.isoformat(),'right':'C','strike':600.,'multiplier':100,
                     'bid':1.9,'ask':2.,'volume':100.,'open_interest':500.,'iv':.2,'last':1.95,
                     'status':status,'received_at':(NOW-timedelta(seconds=8)).isoformat()}]}


def test_preserves_receipt_provenance_and_never_verifies_exchange_time():
    provider = IBKRDataProvider(lambda *args: response())
    snap = provider.snapshot('SPY')
    assert not snap.fictional and not snap.timestamp_verified
    assert snap.source == 'ibkr-shared-research-only'
    assert snap.as_of == NOW-timedelta(seconds=8)
    assert snap.rows[0].open_interest == 500
    assert not snap.rows[0].to_quote(snap.as_of, snap.source, snap.timestamp_verified).timestamp_verified
    assert snapshot_from_dict(snapshot_to_dict(snap)) == snap


@pytest.mark.parametrize('status',['FROZEN','DELAYED','DELAYED_FROZEN','STALE','DISCONNECTED','MISSING','UNKNOWN','MARKET_CLOSED'])
def test_non_live_rows_are_never_usable(status):
    assert not IBKRDataProvider(lambda *args: response(status)).snapshot('SPY').rows


def test_failure_raises_instead_of_silent_yahoo_fallback():
    def fail(*_args):
        raise RuntimeError('service unavailable')
    with pytest.raises(RuntimeError):
        IBKRDataProvider(fail).snapshot('SPY')


def test_executable_quotes_withheld_for_every_ledger():
    transport = Mock()
    assert IBKRDataProvider(transport).quotes_for([CONTRACT]) == []
    transport.assert_not_called()


def test_unverified_ibkr_can_never_bypass_risk_with_legacy_allow_flag():
    quote = replace(make_quote(verified=False), source='ibkr-shared-research-only')
    policy = RiskPolicy(require_verified_quote_time=False)
    for side in [Side.BUY_TO_OPEN, Side.SELL_TO_CLOSE]:
        decision = evaluate(make_intent(side=side), quote, Account(100000,100000,0),
                            [Position(CONTRACT,4,2.)], policy, now=NOW, kill_switch=False)
        assert not decision.allowed
        assert any('not verified' in f for f in decision.failures)


def test_experimental_contract_selector_honors_data_veto():
    snap = IBKRDataProvider(lambda *args: response()).snapshot('SPY')
    assert pick_contract(snap, Right.CALL, NOW, SWING_BASE) is None


def test_health_exposes_no_exception_text():
    def fail(*args, **kwargs):
        raise RuntimeError('secret must not be shown')
    assert IBKRDataProvider(fail).health() == {'state':'UNAVAILABLE','connected':False,'execution_eligible':False}


def test_redirect_forbidden_to_keep_token_local():
    with pytest.raises(RuntimeError):
        NoRedirect().redirect_request(None, None, 302, '', {}, 'https://example.com')


class Clock:
    def __init__(self, at):
        self.at = at

    def __call__(self):
        return self.at


def bars_for(calls, fail=()):
    def transport(resource, params=None, **_kw):
        assert resource == 'history'
        calls.append(params['symbol'])
        if params['symbol'] in fail:
            raise RuntimeError('503')
        return {'bars': [{'timestamp': '2026-11-24', 'close': 10., 'volume': 1.}]}
    return transport


def test_daily_bars_respect_the_shared_budget_and_fill_from_cache_over_time():
    from optplat import ibkr_data
    calls, clock = [], Clock(NOW)
    p = IBKRDataProvider(bars_for(calls), clock=clock)
    names = [f'N{i:03d}' for i in range(40)]
    first = p.daily_bars(names)
    assert len(first) == ibkr_data.DAILY_BUDGET and len(calls) == ibkr_data.DAILY_BUDGET
    again = p.daily_bars(names)                      # same window: cached names only, no new requests
    assert set(again) == set(first) and len(calls) == ibkr_data.DAILY_BUDGET
    clock.at = NOW + timedelta(seconds=ibkr_data.DAILY_WINDOW_S + 1)
    later = p.daily_bars(names)                      # next window: the next names, cached ones still served
    assert len(later) == 2 * ibkr_data.DAILY_BUDGET and len(calls) == 2 * ibkr_data.DAILY_BUDGET


def test_daily_cache_never_outlives_the_new_york_day_or_its_ttl():
    from optplat import ibkr_data
    calls, clock = [], Clock(NOW)
    p = IBKRDataProvider(bars_for(calls), clock=clock)
    p.daily_bars(['SPY'])
    clock.at = NOW + timedelta(seconds=ibkr_data.DAILY_TTL_S + 1)
    p.daily_bars(['SPY'])
    clock.at = NOW + timedelta(days=1)
    p.daily_bars(['SPY'])
    assert calls == ['SPY', 'SPY', 'SPY']


def test_one_failing_name_and_index_symbols_do_not_sink_the_batch():
    calls = []
    p = IBKRDataProvider(bars_for(calls, fail={'BAD'}), clock=Clock(NOW))
    out = p.daily_bars(['SPY', 'BAD', '^VIX', 'QQQ'])
    assert set(out) == {'SPY', 'QQQ'} and '^VIX' not in calls


def test_usage_counts_what_this_platform_sent_by_caller_kind_and_refusal():
    from optplat.ibkr_data import ServiceError
    from optplat.fallback_data import IBKRWithYahooFallback
    now = [datetime(2026, 11, 27, 15, 0, tzinfo=timezone.utc)]

    def transport(resource, params=None, **_kw):
        if resource == 'history' and params.get('interval') == '5 mins':
            raise ServiceError('HTTP 503 Historical pacing budget exhausted')
        return {'bars': []}

    p = IBKRDataProvider(transport, clock=lambda: now[0])
    p.daily_bars(['AAA', 'BBB'])
    with pytest.raises(ServiceError):
        p.intraday_bars('AAA')
    u = p.usage()
    assert u['sent'] == 3 and u['budgeted_sent'] == 3
    assert u['by_caller'] == {'other': {'bars_daily': 2, 'bars_5min': 1}}  # called from the test, not a platform module
    assert u['refused'] == {'HTTP 503 Historical pacing budget exhausted': 1}
    now[0] += timedelta(seconds=601)
    assert p.usage()['sent'] == 0  # only the service's 10-minute window counts
    p.daily_bars(['CCC'])
    assert IBKRWithYahooFallback(p, lambda: None).health()['platform_usage']['sent'] == 1


def _bar_transport(calls):
    def transport(resource, params=None, **_kw):
        calls.append(params['symbol'])
        return {'bars': [{'timestamp': '2026-11-27T15:00:00+00:00', 'open': 1, 'high': 1, 'low': 1, 'close': 1, 'volume': 1}]}
    return transport


def test_five_minute_bars_are_fetched_once_per_completed_bar():
    from optplat.ibkr_data import BAR_SETTLE_S
    calls, now = [], [datetime(2026, 11, 27, 15, 1, tzinfo=timezone.utc)]
    p = IBKRDataProvider(_bar_transport(calls), clock=lambda: now[0])
    first = p.intraday_bars('SPY')
    now[0] = datetime(2026, 11, 27, 15, 5, BAR_SETTLE_S - 1, tzinfo=timezone.utc)  # the 15:05 bar is not complete yet
    assert p.intraday_bars('SPY') is first and calls == ['SPY']
    now[0] = datetime(2026, 11, 27, 15, 5, BAR_SETTLE_S + 1, tzinfo=timezone.utc)
    p.intraday_bars('SPY')
    assert calls == ['SPY', 'SPY']


def test_bar_fetches_stay_inside_the_platform_share_and_core_names_come_first():
    from optplat.ibkr_data import INTRADAY_CORE, INTRADAY_SHARE, BudgetHeld
    calls, now = [], [datetime(2026, 11, 27, 15, 1, tzinfo=timezone.utc)]
    p = IBKRDataProvider(_bar_transport(calls), clock=lambda: now[0])
    extras = [f'X{i}' for i in range(INTRADAY_SHARE)]
    for s in extras[:INTRADAY_SHARE // 2]:
        p.intraday_bars(s)
    with pytest.raises(BudgetHeld):
        p.intraday_bars(extras[-1])          # other names stop at half the share
    for s in INTRADAY_CORE:                  # core names may use the rest of the share
        p.intraday_bars(s)
    n = len(calls)
    now[0] += timedelta(seconds=300)        # the next bar: SPY's cached bars are out of date
    with pytest.raises(BudgetHeld):
        p.intraday_bars('SPY')               # the whole share is used
    assert len(calls) == n == INTRADAY_SHARE  # a held request never reaches the service
    u = p.usage()
    assert u['by_caller']['other']['bars_5min_held'] == 2 and u['budgeted_sent'] == INTRADAY_SHARE
    now[0] += timedelta(seconds=601)
    p.intraday_bars('SPY')                   # the share frees with the service's 10-minute window
    assert len(calls) == INTRADAY_SHARE + 1


def test_core_bar_names_match_the_short_term_lane():
    from optplat import shortterm
    from optplat.ibkr_data import INTRADAY_CORE
    assert tuple(INTRADAY_CORE) == tuple(shortterm.LANE_SYMBOLS)


def test_a_held_bar_request_falls_to_the_research_fallback_and_says_why():
    from optplat.fallback_data import IBKRWithYahooFallback
    from optplat.ibkr_data import BudgetHeld

    class Held(IBKRDataProvider):
        def intraday_bars(self, symbol):
            raise BudgetHeld('platform share of IBKR 5-minute bars used (12/12 per 10 min)')

    class Y:
        def intraday_bars(self, symbol):
            return ['yahoo-bar']

    w = IBKRWithYahooFallback(Held(lambda *a, **k: {}), Y, clock=lambda: NOW)
    assert w.intraday_bars('AMD') == ['yahoo-bar']
    assert 'platform share' in w.last_fallback['why']
