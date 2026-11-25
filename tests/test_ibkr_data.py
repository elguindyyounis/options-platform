"""Synthetic protocol fixtures only; no live connection or performance claim."""
from dataclasses import replace
from datetime import timedelta
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
