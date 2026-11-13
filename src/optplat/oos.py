"""Research-only out-of-sample gate and multiple-lane caveat. Pure functions; they never trade.

Two ways a paper result can look better than it is:

* The same trades are used to pick a lane/setting and to judge it. ``oos_report`` splits closed
  trades chronologically (earlier = selection window, later = test window) and withholds the test
  numbers unless both windows are big enough. The split is by time, never shuffled.
* Many lanes are watched and the best one is quoted. ``best_of_k_null_prob`` gives the chance that
  at least one of ``k`` lanes with NO edge (a 50% coin) shows this many wins in ``n`` trades.

Nothing here proves an edge. Thresholds are research judgement values, not calibrated, and gate
labels only, never trading, risk limits or lane sizes.
"""
from __future__ import annotations

import math
from datetime import datetime
from typing import Any, Iterable, Mapping

MIN_TOTAL = 60
MIN_TEST = 20
TEST_FRACTION = 0.3
INSUFFICIENT = "INSUFFICIENT_SAMPLE"
EVALUATED = "EVALUATED_OUT_OF_SAMPLE"
NOTE = (
    "Simulated fills on recorded quotes. An out-of-sample window reduces, but does not remove, "
    "selection bias. Not a forecast and not evidence of an edge."
)


def _stats(pnls: list[float]) -> dict[str, Any]:
    n = len(pnls)
    wins = sum(1 for p in pnls if p > 0)
    return {
        "trades": n,
        "wins": wins,
        "total_pnl": round(sum(pnls), 2),
        "mean_pnl": round(sum(pnls) / n, 2) if n else None,
        "vs_do_nothing": round(sum(pnls), 2),  # do-nothing earns exactly 0
    }


def oos_report(trades: Iterable[Mapping[str, Any]], test_fraction: float = TEST_FRACTION) -> dict[str, Any]:
    """Chronological split of closed trades; each needs ``closed_at`` (datetime) and ``pnl`` (number).

    Trades with a missing/invalid time or pnl are counted in ``excluded`` rather than dropped silently.
    The test window is only summarised when the total and the test window both meet the minimums.
    """
    good: list[tuple[datetime, float]] = []
    excluded = 0
    for t in trades:
        when, pnl = t.get("closed_at"), t.get("pnl")
        if (
            not isinstance(when, datetime)
            or isinstance(pnl, bool)
            or not isinstance(pnl, (int, float))
            or not math.isfinite(pnl)
        ):
            excluded += 1
            continue
        good.append((when, float(pnl)))
    good.sort(key=lambda x: x[0])
    frac = min(max(test_fraction, 0.1), 0.5)
    n_test = int(round(len(good) * frac))
    train, test = good[: len(good) - n_test], good[len(good) - n_test :]
    out: dict[str, Any] = {
        "status": INSUFFICIENT,
        "excluded": excluded,
        "selection_window": _stats([p for _, p in train]),
        "test_window": None,
        "min_total": MIN_TOTAL,
        "min_test": MIN_TEST,
        "note": NOTE,
    }
    if len(good) >= MIN_TOTAL and n_test >= MIN_TEST:
        out["status"] = EVALUATED
        out["test_window"] = _stats([p for _, p in test])
    return out


def best_of_k_null_prob(wins: int, n: int, k: int, p: float = 0.5) -> float | None:
    """P(at least one of k independent no-edge lanes has >= ``wins`` wins in ``n`` trades).

    None for invalid inputs. Assumes independent lanes, which understates the problem when lanes
    share underlyings or days, so treat it as a lower bound on how often luck alone looks this good.
    """
    if n <= 0 or k <= 0 or wins < 0 or wins > n or not 0 < p < 1:
        return None
    tail = sum(math.comb(n, i) * p**i * (1 - p) ** (n - i) for i in range(wins, n + 1))
    return round(1 - (1 - min(tail, 1.0)) ** k, 4)
