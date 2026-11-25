"""Read-only leaderboard over the existing separate options-ledger views."""
from .strategy_comparison import compare


def build(rows, now, *, fictional=False, history_complete=True):
    groups={}
    for r in rows:
        if r['instrument']!='options':
            continue
        key=r['source']
        account=groups.setdefault(key,{'id':key,'name':r['source_label'],'incumbent':key=='main','trades':[],
                                       'native_starting_capital_usd':None,'native_realized_pnl_usd':0.,
                                       'native_closed_trades':0,'native_open_positions':0})
        quantity=r.get('quantity')
        entry=r.get('entry_price')
        exit_=r.get('exit_price')
        closed=r.get('status')=='CLOSED'
        account['native_realized_pnl_usd']+=r.get('pnl') or 0 if closed else 0
        account['native_closed_trades']+=int(closed)
        account['native_open_positions']+=int(not closed)
        account['trades'].append({'id':r['id'],'symbol':r['symbol'],'opened_at':r.get('opened_at'),
                                  'closed_at':r.get('closed_at') if closed else None,
                                  'original_quantity':quantity,'entry_per_contract':entry*100 if entry is not None else None,
                                  'exit_per_contract':exit_*100 if exit_ is not None else None,
                                  'synthetic':fictional or r.get('synthetic') is True,
                                  'provenance_unknown':key=='main' and r.get('synthetic') is None,
                                  'partial_exits':bool(r.get('partial_exits'))})
    result=compare(list(groups.values()),now=now,history_complete=history_complete)
    result['limitations'].append('Native account capital is not carried by the trade view; no native account return is inferred.')
    return result
