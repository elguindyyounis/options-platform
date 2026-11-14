"""Sample-size honesty for paper results. Display-only: nothing here changes what is traded.

A win rate on a handful of simulated trades is noise. These helpers attach the uncertainty and the
sample status to every headline number so a small lucky streak cannot look like a result.
"""
from __future__ import annotations

import math
from typing import Any, Sequence

MIN_TRADES_FOR_READING = 30  # below this the numbers are labelled INSUFFICIENT; this is a label only
_Z95 = 1.96


def wilson_interval_pct(wins: int, n: int) -> tuple[float, float] | None:
    """95% Wilson score interval for a win rate, in percent. None when there are no trades."""
    if n <= 0 or wins < 0 or wins > n:
        return None
    p = wins / n
    denom = 1 + _Z95**2 / n
    centre = (p + _Z95**2 / (2 * n)) / denom
    half = _Z95 * math.sqrt(p * (1 - p) / n + _Z95**2 / (4 * n**2)) / denom
    return round(max(0.0, centre - half) * 100, 1), round(min(1.0, centre + half) * 100, 1)


def sample_status(n: int) -> str:
    if n <= 0:
        return "NO_TRADES"
    return "INSUFFICIENT" if n < MIN_TRADES_FOR_READING else "MINIMUM_MET"


def trade_evidence(closed: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """Uncertainty and concentration of closed paper trades. Rows need ``pnl``, ``entry``, ``exit``."""
    n = len(closed)
    wins = sum(1 for c in closed if c["pnl"] > 0)
    interval = wilson_interval_pct(wins, n)
    returns = sorted(
        (c["exit"] - c["entry"]) / c["entry"] * 100
        for c in closed
        if c.get("entry") and c["entry"] > 0 and c.get("exit") is not None
    )
    gross_profit = sum(c["pnl"] for c in closed if c["pnl"] > 0)
    top_share = round(max(c["pnl"] for c in closed) / gross_profit * 100, 1) if gross_profit > 0 else None
    median = None
    if returns:
        mid = len(returns) // 2
        median = round(returns[mid] if len(returns) % 2 else (returns[mid - 1] + returns[mid]) / 2, 2)
    status = sample_status(n)
    note = (
        f"{n} closed trade(s); fewer than {MIN_TRADES_FOR_READING} is too few to read anything into."
        if status == "INSUFFICIENT"
        else "Enough trades to look at, which is still not proof of an edge."
        if status == "MINIMUM_MET"
        else "No closed trades yet."
    )
    return {
        "sample_status": status,
        "min_trades_for_reading": MIN_TRADES_FOR_READING,
        "win_rate_ci95_pct": list(interval) if interval else None,
        "median_return_pct": median,
        "worst_return_pct": round(returns[0], 2) if returns else None,
        "best_return_pct": round(returns[-1], 2) if returns else None,
        "largest_win_share_of_gross_profit_pct": top_share,
        "note": note,
    }
