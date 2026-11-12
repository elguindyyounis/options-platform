"""An honest lane scoreboard: how much can the closed trades of each lane really tell us?

Display-only research. It changes nothing a lane trades. It answers four questions the plain averages hide:

* What is the average if exits are less friendly than the bid (the stressed view from ``liquidity.py``)?
* How wide is the uncertainty around that average? (a normal-approximation interval on the mean per-trade return)
* Is the average carried by one trade? (the share of total gain that came from the single best trade)
* With several lanes on the table, one of them will look good by luck. The interval is widened for the number of lanes
  compared (Bonferroni), so the lane that happens to be best is judged against a stricter bar.

What it is not: a test of skill or an estimate of future returns. Trades are not independent (stacked entries, one market
regime), returns are fat-tailed, and the interval ignores both, so it is still too optimistic. Fewer than
``MIN_TRADES_FOR_VERDICT`` closed trades is always reported as too few to say.
"""
from __future__ import annotations

from math import sqrt
from statistics import NormalDist, mean, median, stdev
from typing import Any, Optional

MIN_TRADES_FOR_VERDICT = 30
ALPHA = 0.05

NOTE = (
    f"Per-trade returns as a share of the premium paid. A lane needs {MIN_TRADES_FOR_VERDICT} closed trades before this "
    "says anything, and the interval is widened for the number of lanes compared. Trades overlap and stacked entries are "
    "not independent, so even a clear result here is a reason to keep testing, not proof of an edge."
)


def _rets(closed: list[dict[str, Any]]) -> list[tuple[float, float]]:
    """(bid-exit net %, stressed net %) for each closed trade that carries a post-mortem."""
    out = []
    for t in closed:
        pm = (t.get("close_payload") or {}).get("postmortem")
        if not pm or pm.get("net_pct") is None:
            continue
        net = float(pm["net_pct"])
        stress = pm.get("stress_net_pct")
        out.append((net, net if stress is None else float(stress)))  # no stress number: do not invent a better or worse one
    return out


def _interval(values: list[float], comparisons: int) -> Optional[tuple[float, float]]:
    if len(values) < 2:
        return None
    z = NormalDist().inv_cdf(1 - ALPHA / 2 / max(1, comparisons))
    half = z * stdev(values) / sqrt(len(values))
    m = mean(values)
    return round(m - half, 1), round(m + half, 1)


def lane_scoreboard(closed: list[dict[str, Any]], comparisons: int = 1) -> dict[str, Any]:
    pairs = _rets(closed)
    bid = [b for b, _ in pairs]
    stress = [s for _, s in pairs]
    n = len(pairs)
    row: dict[str, Any] = {"trades": n, "avg_net_pct": None, "avg_stressed_pct": None, "median_net_pct": None, "interval_pct": None,
                           "winners_pct": None, "winners_stressed_pct": None, "best_trade_share_pct": None, "verdict": "NO_TRADES"}
    if not n:
        return row
    row.update(avg_net_pct=round(mean(bid), 1), avg_stressed_pct=round(mean(stress), 1), median_net_pct=round(median(bid), 1),
               winners_pct=round(100 * sum(1 for x in bid if x > 0) / n, 1),
               winners_stressed_pct=round(100 * sum(1 for x in stress if x > 0) / n, 1))
    gains = sum(x for x in bid if x > 0)
    row["best_trade_share_pct"] = round(100 * max(bid) / gains, 1) if gains > 0 and max(bid) > 0 else None
    # the verdict is judged on the stressed series, the stricter of the two views
    iv = _interval(stress, comparisons)
    row["interval_pct"] = iv
    if n < MIN_TRADES_FOR_VERDICT or iv is None:
        row["verdict"] = "TOO_FEW"
    elif iv[0] > 0:
        row["verdict"] = "ABOVE_ZERO"
    elif iv[1] < 0:
        row["verdict"] = "BELOW_ZERO"
    else:
        row["verdict"] = "INDISTINGUISHABLE_FROM_ZERO"
    if row["verdict"] in ("ABOVE_ZERO", "INDISTINGUISHABLE_FROM_ZERO") and row["avg_stressed_pct"] > 0 and (row["best_trade_share_pct"] or 0) >= 50:
        row["verdict"] = "CARRIED_BY_ONE_TRADE"  # a positive average that one trade supplies more than half of is not a lane result
    return row


def scoreboard(by_lane: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    """``by_lane`` maps a lane name to its closed trades. The multiple-comparisons widening uses every lane compared."""
    k = len(by_lane)
    return {"lanes": {name: lane_scoreboard(rows, k) for name, rows in by_lane.items()}, "lanes_compared": k, "note": NOTE}
