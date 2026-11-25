"""Synthetic comparison and interface regressions, not performance evidence."""
from datetime import timedelta
from pathlib import Path
import json
import subprocess

import pytest

from helpers import NOW
from optplat.leaderboard import build
from optplat.strategy_comparison import compare, replay


def trade(**values):
    return dict(id='t',symbol='TEST',opened_at=(NOW-timedelta(days=2)).isoformat(),closed_at=NOW.isoformat(),
                entry_per_contract=100.,exit_per_contract=150.,original_quantity=1,synthetic=False)|values


def test_common_cost_overlay_is_independent_of_native_contract_count():
    result=compare([{'id':'a','trades':[trade(original_quantity=100)]},
                    {'id':'b','trades':[trade(original_quantity=1)]}],now=NOW)
    a,b=result['accounts']
    assert a['comparison']==b['comparison']
    assert a['comparison']['net_pnl_usd']==427.05
    assert result['validated_champion_id'] is None


def test_future_exit_reserves_capital_and_synthetic_never_counts():
    out=replay([trade(closed_at=(NOW+timedelta(days=1)).isoformat()),trade(synthetic=True)],NOW-timedelta(days=3),NOW)
    assert out['open_trades']==1 and out['closed_trades']==0
    assert out['capital_loss_floor_return_pct']<0
    assert out['excluded']['synthetic']==1


def test_truncated_history_never_names_a_leader():
    result=compare([{'id':'a','trades':[trade()]}],now=NOW,history_complete=False)
    assert result['observed_leader_id'] is None


def test_adapter_separates_shares_and_excludes_fictional_results():
    row=dict(id='1',source='main',source_label='Incumbent',instrument='options',symbol='TEST',
             quantity=1,entry_price=1.,exit_price=1.5,pnl=50.,status='CLOSED',
             opened_at=(NOW-timedelta(days=2)).isoformat(),closed_at=NOW.isoformat())
    result=build([row,row|{'instrument':'shares','source':'shares'}],NOW,fictional=True)
    assert len(result['accounts'])==1
    assert result['accounts'][0]['comparison']['closed_trades']==0
    assert result['observed_leader_id'] is None


def test_ui_data_status_requires_valid_stream_evidence_and_has_separate_execution():
    root=Path(__file__).parents[1]/'src/optplat/static'
    js=(root/'app.js').read_text()
    fn=js[js.index('  function dataEvidence('):js.index('  function renderStrategyBoard(')]
    result=subprocess.run(['node','-e',fn+'''
const h={market_data:{connected:true,state:'CONNECTED',observed_market_data_type:1}};
const s={data_source:{name:'ibkr'}};
if(dataEvidence(h,s).label==='IBKR Live Data')throw Error('Missing evidence labeled live');
h.market_data.last_successful_quote_update=new Date().toISOString();h.market_data.entitlement_evidence='BBO event';
if(dataEvidence(h,s).label!=='IBKR Live Data')throw Error('Valid stream not recognized');
h.market_data.last_successful_quote_update=new Date(Date.now()-31000).toISOString();
if(dataEvidence(h,s).label!=='Stale Data')throw Error('Old receipt labeled live');
h.market_data.connected=false;if(dataEvidence(h,s).label!=='Disconnected')throw Error('Disconnected labeled live');
'''],text=True,capture_output=True)
    assert result.returncode==0,result.stderr
    html=(root/'index.html').read_text()
    assert html.index('Strategy performance leaderboard')<html.index('Incumbent benchmark · native ledger')
    assert 'Paper Execution' in js and 'Validated trading champion: Not established' in js
    assert 'REAL + DEMO' not in js


def test_synthetic_startup_requires_explicit_in_memory_fixture(monkeypatch,tmp_path):
    import optplat.__main__ as main
    monkeypatch.setattr(main,'choose_port',lambda *_:8898)
    monkeypatch.setenv('OPTPLAT_API_TOKEN','test-token-never-used-1234')
    monkeypatch.setenv('OPTPLAT_DATA','demo')
    monkeypatch.setenv('OPTPLAT_BROKER','sim')
    monkeypatch.setenv('OPTPLAT_TEST_FIXTURES','1')
    monkeypatch.setenv('OPTPLAT_DB',str(tmp_path/'paper.db'))
    with pytest.raises(SystemExit,match='isolated in-memory'):
        main.main()
    assert not (tmp_path/'paper.db').exists()
