"""Honest closed-trade summary for paper results.

Research display only: it reads filled SELL_TO_CLOSE orders and never changes what is traded. A
number here is a description of simulated fills, not evidence of an edge. The summary refuses to
call anything a "result" below ``min_trades`` closed trades, never reports a 0% win rate for zero
trades, and says what it leaves out (commissions, open-position losses, quote-time verification).
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Callable, Iterable

from .broker.base import QuoteUnavailable
from .models import Order, OrderState, Position, Quote, Side

DEFAULT_MIN_TRADES = 30
CURVE_POINTS = 20  # most recent closed trades shown in the cumulative P&L line

LIMITATIONS = (
    "Simulated fills only; no commissions or exchange fees are modeled, so real costs would be higher.",
    "Closed-trade figures exclude open positions; see open_positions for marks (bid-based, never guessed).",
    "Max drawdown is measured on the closed-trade equity curve only and understates account drawdown.",
    "Trades are grouped per fill, not per independent idea; correlated trades overstate the sample.",
    "Not evidence of an edge. Synthetic or unverified-quote runs prove nothing about real markets.",
)


def describe_fill_model(broker: Any) -> dict[str, Any]:
    """Name how fills are simulated, from the broker itself; unknown stays unknown (display only)."""
    mode = getattr(getattr(broker, "mode", None), "value", None) or str(getattr(broker, "mode", "unknown"))
    slip = getattr(broker, "slippage_pct", None)
    if not isinstance(slip, (int, float)) or isinstance(slip, bool):
        return {"mode": mode, "buys": "unknown", "sells": "unknown", "slippage_pct": None,
                "commissions_modeled": False,
                "note": "Fill model not reported by this broker; do not assume it is conservative."}
    return {"mode": mode, "buys": "ask plus slippage", "sells": "bid minus slippage", "slippage_pct": float(slip),
            "commissions_modeled": False,
            "note": "Immediate simulated fills at the quoted ask/bid; no queue position, partial fills or market impact."}


def closed_trade_pnl(order: Order) -> float | None:
    """Realised P&L in dollars for one fully filled sell-to-close, or None if it cannot be computed."""
    if order.intent.side is not Side.SELL_TO_CLOSE or order.state is not OrderState.FILLED:
        return None
    if order.cost_basis is None or order.avg_fill_price is None or order.filled_qty <= 0:
        return None
    return (order.avg_fill_price - order.cost_basis) * order.filled_qty * order.intent.contract.multiplier


def split_half_check(pnls: list[float], *, min_trades: int = DEFAULT_MIN_TRADES) -> dict[str, Any]:
    """Compare the earlier and later half of closed trades (chronological, no tuning, no peeking).

    This is a stability check, not an out-of-sample test: nothing was fit on the first half. It only
    says whether the sign of the result survives into the later trades. Below ``min_trades`` it
    reports no numbers at all.
    """
    n = len(pnls)
    if n < min_trades:
        return {"status": "INSUFFICIENT_SAMPLE", "first_half_pnl_usd": None, "second_half_pnl_usd": None,
                "consistent": None}
    first, second = sum(pnls[: n // 2]), sum(pnls[n // 2:])
    consistent = (first > 0) == (second > 0) and first != 0 and second != 0
    return {"status": "CHECKED", "trades_per_half": [n // 2, n - n // 2],
            "first_half_pnl_usd": round(first, 2), "second_half_pnl_usd": round(second, 2),
            "consistent": consistent,
            "note": "Same-sign halves are necessary, not sufficient; opposite signs mean the total is unstable."}


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
    cumulative, running = [], 0.0
    longest = current = 0
    for p in pnls:
        running += p
        cumulative.append(round(running, 2))
        current = current + 1 if p < 0 else 0
        longest = max(longest, current)
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
        "split_half": split_half_check(pnls, min_trades=min_trades),
        "longest_losing_streak": longest if n else None,
        "cumulative_pnl_recent_usd": cumulative[-CURVE_POINTS:],
        "cumulative_pnl_points_total": n,
        "limitations": list(LIMITATIONS),
    }


def summarize_open_positions(
    positions: Iterable[Position],
    get_quote: Callable[..., Quote],
    now: datetime,
    *,
    max_age_seconds: float = 120.0,
) -> dict[str, Any]:
    """Mark open long options to the BID (what a sell would get), conservatively.

    A position is marked only with a valid, venue-timestamped, fresh quote. Anything else is listed
    as unmarked and the total is ``None``: a partial total would hide the losses we could not see.
    """
    marked: list[dict[str, Any]] = []
    unmarked: list[dict[str, Any]] = []
    total = 0.0
    for pos in positions:
        label = pos.contract.to_dict()
        reason = None
        quote = None
        try:
            quote = get_quote(pos.contract)
        except QuoteUnavailable:
            reason = "no_quote"
        except Exception:  # fail closed: any broker error means "cannot mark"
            reason = "quote_error"
        if quote is not None:
            if not quote.is_valid():
                reason = "invalid_quote"
            elif not quote.timestamp_verified:
                reason = "quote_time_unverified"
            elif not 0 <= quote.age_seconds(now) <= max_age_seconds:
                reason = "stale_quote"
        if reason or quote is None:
            unmarked.append({"contract": label, "quantity": pos.quantity, "reason": reason})
            continue
        pnl = (quote.bid - pos.avg_cost) * pos.quantity * pos.contract.multiplier
        total += pnl
        marked.append({"contract": label, "quantity": pos.quantity, "avg_cost": pos.avg_cost,
                       "bid": quote.bid, "unrealized_pnl_usd": round(pnl, 2)})
    return {
        "open_positions": len(marked) + len(unmarked),
        "marked": marked,
        "unmarked": unmarked,
        "unrealized_pnl_usd": None if unmarked else round(total, 2),
        "basis": "bid, verified fresh quotes only; total is null if any position cannot be marked",
    }
