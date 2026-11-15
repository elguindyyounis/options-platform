"""Honest summary statistics for closed paper trades. Display-only: nothing here gates an order.

Idea borrowed from the alerter's strategy_performance.py: report profit factor and closed-trade
drawdown, return null instead of a made-up number, and say plainly what the numbers cannot show.
"""
from __future__ import annotations

import math
from typing import Any, Sequence

# Below this many closed trades no win rate or P&L is treated as evidence of anything.
MIN_TRADES_FOR_EVIDENCE = 30


def wilson_interval(wins: int, n: int, z: float = 1.96) -> tuple[float, float] | None:
    """95% Wilson score interval for a win rate, in percent. None when there are no trades."""
    if n <= 0:
        return None
    p = wins / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return round(max(0.0, centre - half) * 100, 1), round(min(1.0, centre + half) * 100, 1)


def summarize_closed(closed: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """`closed` rows need pnl, entry, exit, quantity; order is oldest-first for drawdown."""
    n = len(closed)
    pnls = [float(c["pnl"]) for c in closed]
    wins = sum(1 for x in pnls if x > 0)
    gross_win = sum(x for x in pnls if x > 0)
    gross_loss = -sum(x for x in pnls if x < 0)
    running = peak = max_dd = 0.0
    for x in pnls:
        running += x
        peak = max(peak, running)
        max_dd = max(max_dd, peak - running)
    returns = [(c["exit"] / c["entry"] - 1) * 100 for c in closed if c.get("entry")]
    best = max(pnls) if pnls else None
    ci = wilson_interval(wins, n)
    enough = n >= MIN_TRADES_FOR_EVIDENCE
    return {
        "sample_label": "SAMPLE_TOO_SMALL" if not enough else "MINIMUM_SAMPLE_MET",
        "min_trades_for_evidence": MIN_TRADES_FOR_EVIDENCE,
        "profit_factor": round(gross_win / gross_loss, 3) if gross_loss > 0 else None,
        "avg_trade_return_pct": round(sum(returns) / len(returns), 2) if returns else None,
        "win_rate_ci95_pct": list(ci) if ci else None,
        "max_closed_drawdown_usd": round(max_dd, 2) if n else None,
        "best_trade_share_of_gross_wins_pct": round(best / gross_win * 100, 1)
        if gross_win > 0 and best is not None and best > 0 else None,
        "limitations": "Closed-trade drawdown excludes unrealized losses. Fills are simulated "
        "(ask/bid plus slippage), not broker fills. Even a met minimum sample proves no edge.",
    }
