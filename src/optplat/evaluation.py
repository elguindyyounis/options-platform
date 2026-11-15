"""Honest closed-trade summary for paper results.

Research display only: it reads filled SELL_TO_CLOSE orders and never changes what is traded. A
number here is a description of simulated fills, not evidence of an edge. The summary refuses to
call anything a "result" below ``min_trades`` closed trades, never reports a 0% win rate for zero
trades, and says what it leaves out (commissions, open-position losses, quote-time verification).
"""
from __future__ import annotations

from typing import Any, Iterable

from .models import Order, OrderState, Side

DEFAULT_MIN_TRADES = 30

LIMITATIONS = (
    "Simulated fills only; no commissions or exchange fees are modeled, so real costs would be higher.",
    "Closed trades only: unrealized losses on open positions are excluded, so this is not account P&L.",
    "Max drawdown is measured on the closed-trade equity curve only and understates account drawdown.",
    "Trades are grouped per fill, not per independent idea; correlated trades overstate the sample.",
    "Not evidence of an edge. Synthetic or unverified-quote runs prove nothing about real markets.",
)


def closed_trade_pnl(order: Order) -> float | None:
    """Realised P&L in dollars for one fully filled sell-to-close, or None if it cannot be computed."""
    if order.intent.side is not Side.SELL_TO_CLOSE or order.state is not OrderState.FILLED:
        return None
    if order.cost_basis is None or order.avg_fill_price is None or order.filled_qty <= 0:
        return None
    return (order.avg_fill_price - order.cost_basis) * order.filled_qty * order.intent.contract.multiplier


def summarize_closed_trades(
    orders: Iterable[Order], *, min_trades: int = DEFAULT_MIN_TRADES, starting_equity: float = 100_000.0
) -> dict[str, Any]:
    rows = []
    unpriced = 0
    for o in orders:
        if o.intent.side is Side.SELL_TO_CLOSE and o.state is OrderState.FILLED:
            pnl = closed_trade_pnl(o)
            if pnl is None:
                unpriced += 1  # filled exit without a recorded cost basis: counted, never guessed
            else:
                rows.append((o.updated_at, o.id, pnl))
    rows.sort()
    pnls = [r[2] for r in rows]
    n = len(pnls)
    wins = sum(p > 0 for p in pnls)
    gross_win = sum(p for p in pnls if p > 0)
    gross_loss = -sum(p for p in pnls if p < 0)
    equity = peak = float(starting_equity)
    max_dd = 0.0
    for p in pnls:
        equity += p
        peak = max(peak, equity)
        if peak > 0:
            max_dd = max(max_dd, 100.0 * (peak - equity) / peak)
    total = sum(pnls)
    if n == 0:
        status = "NO_CLOSED_TRADES"
    elif n < min_trades:
        status = "INSUFFICIENT_SAMPLE"
    else:
        status = "SAMPLE_SIZE_MET_NOT_PROOF_OF_EDGE"
    return {
        "status": status,
        "closed_trades": n,
        "min_trades_required": min_trades,
        "unpriced_exits": unpriced,
        "wins": wins,
        "losses": sum(p < 0 for p in pnls),
        "win_rate_pct": round(100.0 * wins / n, 2) if n else None,
        "realized_pnl_usd": round(total, 2),
        "average_pnl_usd": round(total / n, 2) if n else None,
        "profit_factor": round(gross_win / gross_loss, 3) if gross_loss > 0 else None,
        "best_trade_share_of_gross_wins_pct": round(100.0 * max(pnls) / gross_win, 1) if gross_win > 0 else None,
        "pnl_without_best_trade_usd": round(total - max(pnls), 2) if n else None,
        "closed_trade_max_drawdown_pct": round(max_dd, 3) if n else None,
        "limitations": list(LIMITATIONS),
    }
