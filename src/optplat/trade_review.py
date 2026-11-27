"""A post-mortem for every trade of the main paper account, open or closed (owner request, 2026-11-27).

For each trade it asks two questions, from recorded prices only: did the exit leave money on the table, and was the money
made or lost in the right place? It uses the shadow book's bid path of the same contract (the platform records one for the
contracts it follows) before and after the exit. Without a recorded price after the exit it says UNKNOWN, never a guess.

It diagnoses nothing for certain: one trade proves nothing, and "try next" lines are hypotheses for X1-X6 in
docs/EVOLUTION_PLAN.md, never changes the platform applies by itself. Deterministic, read-only.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

EARLY_BEST = 1.15      # the bid later reached 15% above the exit price ...
EARLY_LAST = 1.05      # ... and was still 5% above it at the last recorded point
RIGHT_LAST = 0.98      # exit looked right when the last later bid was 2%+ below the exit price
GAVE_BACK_PEAK = 20.0  # a gain of 20% was shown during the hold ...
GAVE_BACK_FRAC = 0.5   # ... and less than half of it was kept


def _ts(s: str) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(s)
    except (TypeError, ValueError):
        return None


def index_points(points: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {}
    for p in points:
        if p.get("bid") is not None and p["bid"] >= 0 and _ts(p.get("ts")) is not None:
            out.setdefault(p["contract"], []).append(p)
    for v in out.values():
        v.sort(key=lambda p: p["ts"])
    return out


def review(trade: dict[str, Any], path: list[dict[str, Any]]) -> dict[str, Any]:
    entry = trade["entry_price"]
    notes: list[str] = []
    tags: list[str] = []
    t_in, t_out = _ts(trade["entry_time"]), _ts(trade.get("exit_time"))
    closed = trade["status"] == "CLOSED"
    during = [p for p in path if t_in and _ts(p["ts"]) >= t_in and (t_out is None or _ts(p["ts"]) <= t_out)]
    after = [p for p in path if t_out and _ts(p["ts"]) > t_out]
    peak = max((p["bid"] / entry - 1) * 100 for p in during) if during and entry else None
    out: dict[str, Any] = {"closed": closed, "result": "WIN" if (trade.get("pnl") or 0) > 0 else ("LOSS" if trade.get("pnl") is not None and trade["pnl"] < 0 else "FLAT_OR_OPEN"),
                           "peak_gain_pct_during_hold": None if peak is None else round(peak, 1), "after_exit": None}
    reason = trade.get("exit_reason")
    if reason:
        tags.append(str(reason).upper())
    c = trade.get("committee") or {}
    if c.get("net_score") is not None:
        notes.append(f"Entry: committee net conviction {c['net_score']}, {c.get('quantity')} contract(s).")
    elif trade.get("entry_reason"):
        notes.append(f"Entry reason on record: {trade['entry_reason']}")
    else:
        notes.append("No entry reasoning was recorded for this trade.")
    if not closed:
        out.update(verdict="OPEN", tags=tags, notes=notes + ["Still open: the full review is written when it closes."], try_next=[])
        return out
    pnl_pct = trade.get("pnl_pct")
    try_next: list[str] = []
    if peak is not None and pnl_pct is not None and peak >= GAVE_BACK_PEAK and pnl_pct < peak * GAVE_BACK_FRAC:
        tags.append("GAVE_BACK")
        notes.append(f"It was up {peak:.0f}% during the hold and closed at {pnl_pct:.0f}%: most of the gain was given back.")
        try_next.append("Test banking half at the first strong gain (X5) or letting the exit agent judge it (X6).")
    px = trade.get("exit_price")
    verdict = "UNKNOWN"
    if after and px:
        best, last = max(p["bid"] for p in after), after[-1]["bid"]
        out["after_exit"] = {"points": len(after), "best_bid": best, "last_bid": last, "best_vs_exit_pct": round((best / px - 1) * 100, 1), "last_vs_exit_pct": round((last / px - 1) * 100, 1)}
        if best >= px * EARLY_BEST and last >= px * EARLY_LAST:
            verdict = "EXITED_EARLY"
            notes.append(f"The bid later reached {out['after_exit']['best_vs_exit_pct']:+.0f}% above the exit and was {out['after_exit']['last_vs_exit_pct']:+.0f}% at the last point: profit could have been extended.")
            try_next.append("Test holding while the trend supports the trade (X6) or a trailing stop (X3) on these entries.")
        elif last <= px * RIGHT_LAST:
            verdict = "EXIT_LOOKED_RIGHT"
            notes.append(f"The bid fell {abs(out['after_exit']['last_vs_exit_pct']):.0f}% after the exit: leaving was the better call.")
        else:
            verdict = "EXIT_MIXED"
            notes.append("The price after the exit went both ways: neither clearly early nor clearly right.")
    else:
        notes.append("No bid was recorded after the exit, so whether holding would have paid is unknown.")
    if verdict == "UNKNOWN" and pnl_pct is not None and pnl_pct < 0:
        try_next.append("Record this contract's price path after exits so losses and exits can be judged, not guessed.")
    out.update(verdict=verdict, tags=tags, notes=notes, try_next=try_next,
               caveat="One trade says nothing about an edge; the later path is from recorded delayed data.")
    return out
