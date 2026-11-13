"""An honest lane scoreboard: how much can the closed trades of each lane really tell us?

Display-only research. It changes nothing a lane trades. It answers four questions the plain averages hide:

* What is the average if exits are less friendly than the bid (the stressed view from ``liquidity.py``)?
* How wide is the uncertainty around that average? (a normal-approximation interval on the mean per-trade return)
* Is the average carried by one trade? (the share of total gain that came from the single best trade)
* Are all the closed trades actually in the numbers? A closed trade with no post-mortem cannot be scored. It is counted, and a
  positive reading is withheld (INCOMPLETE_DATA) when more than ``MAX_UNSCORED_SHARE`` of the lane's closed trades are
  unscored, because dropping them can only flatter a lane. Trades scored without a stressed figure are counted too
  (``stress_missing``) but do not change the reading.
* Are the trades really separate bets? Stacked entries on the same name on the same day move together, so they are grouped
  into clusters (same symbol, same entry day) and the interval and the 30-trade bar are computed on cluster means. Ten stacked
  entries on one name count as one observation, not ten.
* With several lanes on the table, one of them will look good by luck. The interval is widened for the number of lanes
  compared (Bonferroni), so the lane that happens to be best is judged against a stricter bar.

What it is not: a test of skill or an estimate of future returns. Clustering removes only the most obvious dependence; one
market regime and fat-tailed returns remain, so the interval is still too optimistic. Fewer than
``MIN_TRADES_FOR_VERDICT`` closed trades is always reported as too few to say.
"""
from __future__ import annotations

from math import sqrt
from statistics import NormalDist, mean, median, stdev
from typing import Any, Optional

MIN_TRADES_FOR_VERDICT = 30
ALPHA = 0.05
MAX_UNSCORED_SHARE = 0.10

NOTE = (
    f"Per-trade returns as a share of the premium paid. A lane needs {MIN_TRADES_FOR_VERDICT} closed trades before this "
    "says anything, and the interval is widened for the number of lanes compared. Trades overlap and stacked entries are "
    "not independent, so even a clear result here is a reason to keep testing, not proof of an edge."
)


def _rets(closed: list[dict[str, Any]]) -> list[tuple[float, float]]:
    """(bid-exit net %, stressed net %) for each closed trade that carries a post-mortem."""
    out, _ = _rets_and_gaps(closed)
    return out


def _cluster_key(t: dict[str, Any]) -> str:
    """Same symbol and same entry day are one cluster. A trade missing either field stands alone (never merged by guess)."""
    sym, opened = t.get("symbol"), t.get("opened_at")
    if not sym or not opened:
        return f"solo:{id(t)}"
    return f"{sym}|{str(opened)[:10]}"


def _clustered(closed: list[dict[str, Any]], stress_index: int) -> list[float]:
    """Mean return per cluster of scored trades; ``stress_index`` 0 picks the bid exit, 1 the stressed exit."""
    groups: dict[str, list[float]] = {}
    for t in closed:
        pm = (t.get("close_payload") or {}).get("postmortem")
        if not pm or pm.get("net_pct") is None:
            continue
        net = float(pm["net_pct"])
        stress = pm.get("stress_net_pct")
        pair = (net, net if stress is None else float(stress))
        groups.setdefault(_cluster_key(t), []).append(pair[stress_index])
    return [mean(v) for v in groups.values()]


def _rets_and_gaps(closed: list[dict[str, Any]]) -> tuple[list[tuple[float, float]], int]:
    """Same as ``_rets`` plus how many scored trades had no stressed figure (the bid number stood in for it)."""
    out = []
    no_stress = 0
    for t in closed:
        pm = (t.get("close_payload") or {}).get("postmortem")
        if not pm or pm.get("net_pct") is None:
            continue
        net = float(pm["net_pct"])
        stress = pm.get("stress_net_pct")
        if stress is None:
            no_stress += 1
        out.append((net, net if stress is None else float(stress)))  # no stress number: do not invent a better or worse one
    return out, no_stress


def _interval(values: list[float], comparisons: int) -> Optional[tuple[float, float]]:
    if len(values) < 2:
        return None
    z = NormalDist().inv_cdf(1 - ALPHA / 2 / max(1, comparisons))
    half = z * stdev(values) / sqrt(len(values))
    m = mean(values)
    return round(m - half, 1), round(m + half, 1)


def lane_scoreboard(closed: list[dict[str, Any]], comparisons: int = 1) -> dict[str, Any]:
    pairs, no_stress = _rets_and_gaps(closed)
    bid = [b for b, _ in pairs]
    stress = [s for _, s in pairs]
    n = len(pairs)
    unscored = len(closed) - n
    row: dict[str, Any] = {"trades": n, "closed_total": len(closed), "clusters": 0, "unscored": unscored, "stress_missing": no_stress, "avg_net_pct": None, "avg_stressed_pct": None, "median_net_pct": None, "interval_pct": None,
                           "winners_pct": None, "winners_stressed_pct": None, "best_trade_share_pct": None, "verdict": "NO_TRADES"}
    if not n:
        return row
    row.update(avg_net_pct=round(mean(bid), 1), avg_stressed_pct=round(mean(stress), 1), median_net_pct=round(median(bid), 1),
               winners_pct=round(100 * sum(1 for x in bid if x > 0) / n, 1),
               winners_stressed_pct=round(100 * sum(1 for x in stress if x > 0) / n, 1))
    gains = sum(x for x in bid if x > 0)
    row["best_trade_share_pct"] = round(100 * max(bid) / gains, 1) if gains > 0 and max(bid) > 0 else None
    # the verdict is judged on the stressed series, the stricter of the two views
    clustered = _clustered(closed, 1)
    row["clusters"] = len(clustered)
    iv = _interval(clustered, comparisons)  # on cluster means: stacked same-name, same-day entries count once
    row["interval_pct"] = iv
    if n < MIN_TRADES_FOR_VERDICT or len(clustered) < MIN_TRADES_FOR_VERDICT or iv is None:
        row["verdict"] = "TOO_FEW"
    elif iv[0] > 0:
        row["verdict"] = "ABOVE_ZERO"
    elif iv[1] < 0:
        row["verdict"] = "BELOW_ZERO"
    else:
        row["verdict"] = "INDISTINGUISHABLE_FROM_ZERO"
    if row["verdict"] == "ABOVE_ZERO" and unscored / len(closed) > MAX_UNSCORED_SHARE:
        row["verdict"] = "INCOMPLETE_DATA"  # a positive reading needs nearly every closed trade scored
    if row["verdict"] in ("ABOVE_ZERO", "INDISTINGUISHABLE_FROM_ZERO") and row["avg_stressed_pct"] > 0 and (row["best_trade_share_pct"] or 0) >= 50:
        row["verdict"] = "CARRIED_BY_ONE_TRADE"  # a positive average that one trade supplies more than half of is not a lane result
    return row


def scoreboard(by_lane: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    """``by_lane`` maps a lane name to its closed trades. The multiple-comparisons widening uses every lane compared."""
    k = len(by_lane)
    return {"lanes": {name: lane_scoreboard(rows, k) for name, rows in by_lane.items()}, "lanes_compared": k, "note": NOTE}
