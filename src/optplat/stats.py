"""Display-only sample-size honesty for paper results. Nothing here influences trading."""
from __future__ import annotations

import math
from typing import Optional

# Below this many closed trades a win rate or P&L total is anecdote, not a result.
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


def sample_assessment(pnls: list[float]) -> dict:
    """Describe how much weight a list of closed-trade P&Ls can bear."""
    n = len(pnls)
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    ci = wilson_interval(len(wins), n)
    status = "INSUFFICIENT" if n < MIN_TRADES_FOR_RESULT else "PRELIMINARY"
    note = (
        f"{n} closed trade(s); fewer than {MIN_TRADES_FOR_RESULT} is anecdote, not a result."
        if status == "INSUFFICIENT"
        else "Enough trades to look at, still paper fills; one regime and no out-of-sample split."
    )
    return {
        "sample_status": status,
        "min_trades_for_result": MIN_TRADES_FOR_RESULT,
        "win_rate_ci95_pct": list(ci) if ci else None,
        "avg_win": round(sum(wins) / len(wins), 2) if wins else None,
        "avg_loss": round(sum(losses) / len(losses), 2) if losses else None,
        "best_trade": round(max(pnls), 2) if pnls else None,
        "worst_trade": round(min(pnls), 2) if pnls else None,
        "sample_note": note,
    }
