"""Read-only common-capital overlay on recorded paper fills, never new trades.

Vendored unchanged in options-platform for a consistent comparison contract.
Native ledgers and decisions are never rewritten. Missing paths cannot validate
a champion; normalizing selected trades cannot normalize missed opportunities.
"""
from collections import defaultdict
from datetime import datetime, timezone
import math

VERSION = 'common-risk-recorded-fill-overlay-v1'
CAPITAL = 100000.
PER_TRADE_PREMIUM = 1000.
TOTAL_PREMIUM = 10000.
PER_SYMBOL_PREMIUM = 2000.
FEE = .65
EXTRA_SLIPPAGE = .005
PROMOTION_CRITERIA = [
    'Frozen, pre-registered strategy and comparator; no retrospective promotion.',
    'At least 60 forward market sessions, 30 closed trades and 20 independent underlying-days.',
    'At least 10 trades in a later 30% holdout; identical timestamps, capital, risk and cost assumptions.',
    'Verified option BBO times and complete quote paths, including rejected opportunities and open losses.',
    '95% date-clustered bootstrap lower bound for after-cost improvement above zero; correct for all trials.',
    'Improvement survives removing the three best trades and worse execution; drawdown respects frozen limits.',
    'Independent risk vetoes remain enforced; a human reviews any champion designation.',
]
DEMOTION_CRITERIA = [
    'Immediately suspend execution on data-quality or hard-risk failure; preserve the incumbent and all ledgers.',
    'Review after a pre-registered holdout shows deterioration, uncertainty crosses the required margin, or risk breaches its frozen limit.',
    'Do not replace the champion merely because another strategy leads a short recent window.',
]


def timestamp(value):
    try:
        result = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        return result.astimezone(timezone.utc) if result.tzinfo else None
    except (ValueError, TypeError, OverflowError):
        return None


def finite(value):
    return type(value) in (float, int) and math.isfinite(value)


def replay(trades, start, end):
    """Integer lots, same capital ceilings, no look-ahead capital reuse.

    Entry/exit are recorded effective fills, with the SAME extra slippage and
    commission overlay. This is not re-pricing from missing historical BBOs.
    Open positions reserve their full premium; no mark or exit is fabricated.
    Partial-exit positions are excluded until their complete dated cash flows
    can be replayed consistently by both adapters.
    """
    events = []
    excluded = defaultdict(int)
    selected = []
    for t in trades:
        opened, closed = timestamp(t.get('opened_at')), timestamp(t.get('closed_at'))
        if closed is not None and closed > end:
            closed = None  # no look-ahead: reserve premium, do not use a later exit
        if t.get('synthetic'):
            excluded['synthetic'] += 1
            continue
        if t.get('provenance_unknown'):
            excluded['historical_data_provenance_unknown'] += 1
            continue
        if opened is None or opened > end:
            excluded['invalid_or_future_time'] += 1
            continue
        if opened < start:
            excluded['before_common_window'] += 1
            continue
        if t.get('partial_exits'):
            excluded['partial_cashflow_path_unavailable'] += 1
            continue
        entry, quantity = t.get('entry_per_contract'), t.get('original_quantity')
        exit_ = t.get('exit_per_contract')
        if (not finite(entry) or entry <= 0 or not finite(quantity) or quantity < 1 or int(quantity) != quantity
                or (closed is not None and (closed < opened
                                           or not finite(exit_) or exit_ < 0))):
            excluded['invalid_fill_evidence'] += 1
            continue
        idx = len(selected)
        selected.append(t)
        events.append((opened, 1, idx))
        if closed is not None:
            events.append((closed, 2 if closed == opened else 0, idx))
    cash, premium, peak, max_dd = CAPITAL, 0., CAPITAL, 0.
    held, outcomes, deployment = {}, [], 0.
    symbol_premium=defaultdict(float)
    independent = set()
    for at, kind, idx in sorted(events):
        t = selected[idx]
        if kind == 1:
            price = t['entry_per_contract']*(1+EXTRA_SLIPPAGE)+FEE
            quantity = math.floor((min(PER_TRADE_PREMIUM, max(0.,TOTAL_PREMIUM-premium),
                                      max(0.,PER_SYMBOL_PREMIUM-symbol_premium[t.get('symbol')]),cash)+1e-9)/price)
            if quantity < 1:
                excluded['capital_risk_or_integer_lot_limit'] += 1
                continue
            cost = quantity*price
            cash -= cost
            premium += cost
            symbol_premium[t.get('symbol')]+=cost
            deployment += cost
            held[idx] = (quantity, cost)
            independent.add((t.get('symbol'), at.date().isoformat()))
        elif idx in held:
            quantity, cost = held.pop(idx)
            proceeds = quantity*(t['exit_per_contract']*(1-EXTRA_SLIPPAGE)-FEE)
            cash += proceeds
            premium -= cost
            symbol_premium[t.get('symbol')]-=cost
            outcomes.append({'pnl':proceeds-cost, 'at':at.isoformat(), 'symbol':t.get('symbol')})
            realized_equity = cash+premium
            peak = max(peak, realized_equity)
            max_dd = max(max_dd, (peak-realized_equity)/peak*100)
    pnl = [x['pnl'] for x in outcomes]
    net = sum(pnl)
    gross_profit = sum(x for x in pnl if x > 0)
    gross_loss = -sum(x for x in pnl if x < 0)
    days = max(1, (end-start).total_seconds()/86400)
    return {'net_pnl_usd':round(net,2), 'return_pct':round(net/CAPITAL*100,4),
            'closed_trades':len(pnl), 'admitted_trades':len(outcomes)+len(held),
            'open_trades':len(held), 'open_premium_reserved_usd':round(premium,2),
            'capital_loss_floor_return_pct':round((net-premium)/CAPITAL*100,4),
            'expectancy_usd':round(net/len(pnl),2) if pnl else None,
            'profit_factor':round(gross_profit/gross_loss,3) if gross_loss > 0 else None,
            'profit_factor_note':'No observed losses; ratio undefined' if pnl and gross_loss == 0 else None,
            'closed_only_drawdown_pct':round(max_dd,4) if pnl else None,
            'full_portfolio_drawdown_pct':None,
            'capital_efficiency_pct':round(net/deployment*100,3) if deployment else None,
            'trades_per_calendar_day':round((len(outcomes)+len(held))/days,3),
            'independent_underlying_days':len(independent), 'excluded':dict(excluded),
            'sample_status':'INSUFFICIENT_FOR_PROMOTION', 'outcomes':outcomes}


def compare(accounts, *, now, history_complete=True):
    """Rank observed, cost-stressed common-risk results; never name a champion."""
    active = [a for a in accounts if any(not t.get('synthetic') and not t.get('provenance_unknown') for t in a.get('trades', []))]
    beginnings = []
    for account in active:
        dates=[timestamp(t.get('opened_at')) for t in account['trades'] if not t.get('synthetic') and not t.get('provenance_unknown')]
        valid=[d for d in dates if d is not None and d <= now]
        if valid:
            beginnings.append(min(valid))
    start = max(beginnings) if beginnings else now
    rows = []
    for account in accounts:
        stats = replay(account.get('trades', []), start, now)
        rows.append({k:v for k,v in account.items() if k != 'trades'} | {'comparison':stats})
    rows.sort(key=lambda r:(r['comparison']['closed_trades'] > 0,
                            r['comparison']['capital_loss_floor_return_pct'],
                            r['comparison']['net_pnl_usd']), reverse=True)
    eligible = [r for r in rows if r['comparison']['closed_trades'] > 0]
    leader = eligible[0]['id'] if eligible and history_complete else None
    return {'version':VERSION, 'as_of':now.isoformat(), 'window_start':start.isoformat(),
            'window_end':now.isoformat(), 'accounts':rows, 'observed_leader_id':leader,
            'validated_champion_id':None, 'champion_status':'NO_INDEPENDENTLY_VALIDATED_CHAMPION',
            'promotion_criteria':PROMOTION_CRITERIA, 'demotion_criteria':DEMOTION_CRITERIA,
            'history_complete':history_complete,
            'assumptions':{'capital_usd':CAPITAL,'per_trade_premium_usd':PER_TRADE_PREMIUM,
                           'total_premium_cap_usd':TOTAL_PREMIUM,'fee_per_contract_each_way_usd':FEE,
                           'per_symbol_premium_cap_usd':PER_SYMBOL_PREMIUM,
                           'extra_slippage_each_way_pct':EXTRA_SLIPPAGE*100,
                           'integer_contracts':True,'writes_ledger':False},
            'ranking_basis':'Realized common-risk net P&L minus all still-open reserved premium; closed outcomes only are descriptive',
            'limitations':['Recorded-fill cost overlay, not a replay from identical historical BBOs.',
                           'Different opportunity sets, prior sizing/admission and incomplete option paths prevent a fair skill claim.',
                           'Open losses, partial-exit exclusions and incomplete histories are disclosed; full drawdown is unavailable.',
                           'Synthetic records are excluded. Native capital, risk and all strategy ledgers remain separate.',
                           'An observed leader is not a validated champion. These criteria are a proposed review policy, not an automatic promotion.']}
