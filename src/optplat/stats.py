"""Small-sample honesty helpers for paper results. Display-only: nothing here gates trading."""
from __future__ import annotations

import math
from typing import Optional, Sequence

# Fewer closed trades than this cannot support any statement about an edge.
MIN_TRADES_FOR_RESULT = 30


def wilson_interval(wins: int, n: int, z: float = 1.96) -> Optional[tuple[float, float]]:
    """95% Wilson score interval for a win rate, in percent. None when there are no trades."""
    if n <= 0 or wins < 0 or wins > n:
        return None
    p = wins / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return round(max(0.0, centre - half) * 100, 1), round(min(1.0, centre + half) * 100, 1)


def sample_quality(pnls: Sequence[float]) -> dict:
    """Describe how much weight a list of closed-trade P&Ls can bear."""
    n = len(pnls)
    wins = sum(1 for p in pnls if p > 0)
    interval = wilson_interval(wins, n)
    total = round(sum(pnls), 2)
    without_best = round(total - max(pnls), 2) if n else None
    status = "NO_TRADES" if n == 0 else "INSUFFICIENT" if n < MIN_TRADES_FOR_RESULT else "MINIMUM_MET"
    return {
        "status": status,
        "min_trades_for_result": MIN_TRADES_FOR_RESULT,
        "win_rate_ci95_pct": list(interval) if interval else None,
        "realized_pnl_without_best_trade": without_best,
        "best_trade_pnl": round(max(pnls), 2) if n else None,
        "worst_trade_pnl": round(min(pnls), 2) if n else None,
        "note": (
            "Not a result: too few closed trades."
            if status != "MINIMUM_MET"
            else "Minimum count met, which is necessary but not sufficient: no out-of-sample split, "
            "and fills are simulated."
        ),
    }
