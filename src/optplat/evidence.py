"""Display-only honesty statistics for paper results. Pure functions; nothing here trades or gates.

Challenge origin: ``report()`` used to print a bare win rate, so one winning trade read as 100%.
The alerter labels its hypothetical outcomes as unverified; this module does the same for the
platform's own paper trades by attaching sample size, an uncertainty interval and a plain verdict.
"""
from __future__ import annotations

import math
from typing import Any, Sequence

# A result is only called a result from this many closed trades. Even then it proves nothing about
# the future; below it the numbers are anecdotes. (Display threshold only; it gates no trading.)
MIN_TRADES_FOR_RESULT = 30

INSUFFICIENT = "INSUFFICIENT_SAMPLE"
PRELIMINARY = "PRELIMINARY"

_Z95 = 1.959964


def wilson_interval(wins: int, n: int, z: float = _Z95) -> tuple[float, float] | None:
    """95% Wilson score interval for a win rate, in percent. None when there are no trades."""
    if n <= 0 or not 0 <= wins <= n:
        return None
    p = wins / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return round(max(0.0, centre - half) * 100, 1), round(min(1.0, centre + half) * 100, 1)


def evidence_summary(pnls: Sequence[float], *, truncated: bool = False) -> dict[str, Any]:
    """Summarise closed-trade P&L with the caveats a reader needs before trusting it."""
    n = len(pnls)
    wins = sum(1 for p in pnls if p > 0)
    total = round(sum(pnls), 2)
    interval = wilson_interval(wins, n)
    best = max(pnls) if pnls else None
    # If one trade is most of the profit, the result is one lucky trade, not a pattern.
    best_share = round(best / total * 100, 1) if best is not None and best > 0 and total > 0 else None
    verdict = INSUFFICIENT if n < MIN_TRADES_FOR_RESULT else PRELIMINARY
    notes = []
    if n < MIN_TRADES_FOR_RESULT:
        notes.append(f"Only {n} closed trades; fewer than {MIN_TRADES_FOR_RESULT} is an anecdote, not a result.")
    if best_share is not None and best_share > 50 and n > 1:
        notes.append(f"The best single trade is {best_share}% of net profit.")
    if truncated:
        notes.append("Order history hit the read limit; older closed trades are missing from these figures.")
    notes.append("Simulated fills, no commissions modelled, no out-of-sample test. This is not evidence of an edge.")
    return {
        "verdict": verdict,
        "closed_trades": n,
        "min_trades_for_result": MIN_TRADES_FOR_RESULT,
        "win_rate_ci95_pct": list(interval) if interval else None,
        "expectancy_per_trade": round(total / n, 2) if n else None,
        "best_trade_share_of_profit_pct": best_share,
        "history_truncated": truncated,
        "notes": notes,
    }
