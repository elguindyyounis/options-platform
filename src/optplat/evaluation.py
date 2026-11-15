"""Research-only honesty layer for paper results.

Pure functions, no I/O. They never influence what is traded; they only qualify how much a set of
closed paper trades can be believed. Paper fills are modeled (ask + slippage in, bid - slippage
out), so even a "sufficient" sample proves nothing about a real edge.
"""
from __future__ import annotations

import math
from typing import Any, Sequence

MIN_TRADES_FOR_RESULT = 30
Z95 = 1.959964


def wilson_interval(wins: int, n: int, z: float = Z95) -> tuple[float, float] | None:
    """95% Wilson score interval for a win rate, in percent. None when n == 0."""
    if n <= 0 or wins < 0 or wins > n:
        return None
    p = wins / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return round(max(0.0, centre - half) * 100, 1), round(min(1.0, centre + half) * 100, 1)


def sample_label(n: int) -> str:
    if n <= 0:
        return "NO_CLOSED_TRADES"
    if n < MIN_TRADES_FOR_RESULT:
        return "INSUFFICIENT_SAMPLE"
    return "SAMPLE_ONLY_NOT_AN_EDGE"


def closed_trade_stats(trades: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """`trades` need `pnl`, `entry`, `exit`, `closed_at` (sortable). Unusable rows are skipped
    and counted, never assumed fine."""
    usable = [
        t for t in trades
        if all(isinstance(t.get(k), (int, float)) and math.isfinite(t[k]) for k in ("pnl", "entry", "exit"))
        and t["entry"] > 0
    ]
    n = len(usable)
    wins = sum(1 for t in usable if t["pnl"] > 0)
    gains = sum(t["pnl"] for t in usable if t["pnl"] > 0)
    losses = -sum(t["pnl"] for t in usable if t["pnl"] < 0)
    # Cumulative realized P&L drawdown in dollars (no starting-equity assumption).
    cum = peak = max_dd = 0.0
    for t in sorted(usable, key=lambda t: str(t.get("closed_at", ""))):
        cum += t["pnl"]
        peak = max(peak, cum)
        max_dd = max(max_dd, peak - cum)
    returns = [(t["exit"] / t["entry"] - 1) * 100 for t in usable]
    return {
        "sample_label": sample_label(n),
        "min_trades_for_result": MIN_TRADES_FOR_RESULT,
        "trades_used": n,
        "trades_skipped_unusable": len(trades) - n,
        "win_rate_ci95_pct": wilson_interval(wins, n),
        "avg_trade_return_pct": round(sum(returns) / n, 2) if n else None,
        "profit_factor": round(gains / losses, 3) if losses > 0 else None,
        "closed_trade_max_drawdown_usd": round(max_dd, 2) if n else None,
        "limitations": (
            "Closed trades only: excludes unrealized declines. Fills are modeled, not broker fills. "
            "The win-rate interval assumes independent trades, which overlapping positions in the "
            "same underlying are not. A sample label is never evidence of an edge."
        ),
    }
