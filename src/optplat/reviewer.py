"""An advisory reviewer for open option positions: "should this one go early, even though neither stop nor target was hit?"

The exit rules (stop, target, expiry, time, trend) are mechanical. This module adds a second opinion at every check and
writes it down, but it never closes anything and changes no exit threshold. What makes it useful and not just opinion is the
scoring: when a position finally closes by its normal rule, each earlier "consider exiting" call is compared with what actually
happened, so after enough trades the data says whether leaving early would have helped, and by how much, or not.

Rules (all use only the premium, so they work for every lane):
  gave_back      the position was up at least 25% at its best and has given back half of that gain
  never_worked   a swing or flow trade held 3+ days, down 10% or more, and never up more than 5%
  late_and_losing a swing or flow trade within 7 days of expiry and still under water (time decay speeds up here)
"""
from __future__ import annotations

import math
from datetime import date, datetime
from typing import Any, Optional

GAVE_BACK_PEAK_PCT = 25.0        # the best gain a position must have shown before giving it back counts
GAVE_BACK_FRACTION = 0.5         # ... and the share of that gain that must be gone
NEVER_WORKED_DAYS = 3
NEVER_WORKED_LOSS_PCT = -10.0
NEVER_WORKED_PEAK_PCT = 5.0
LATE_DTE = 7
MIN_SCORED = 20                  # scored calls a rule needs before the scorecard says anything
CLEAR_PTS = 2.0                  # average gain or loss, in points of the entry premium, that counts as a difference

RULES = {
    "gave_back": "Gave back half of a peak gain of 25% or more",
    "never_worked": "Held 3+ days, down 10% or more, and never up more than 5%",
    "late_and_losing": "Within 7 days of expiry and still under water",
}


def assess(*, kind: str, entry: float, bid: float, peak_bid: float, opened_at: str, expiry: str, now: datetime) -> dict[str, Any]:
    """The review of one open position. Returns facts, any flags raised, and a verdict of HOLD or CONSIDER_EXIT."""
    if not (math.isfinite(entry) and entry > 0 and math.isfinite(bid) and bid >= 0):
        return {"verdict": "UNKNOWN", "flags": [], "pnl_pct": None, "peak_pnl_pct": None, "held_days": None, "dte": None}
    peak = max(peak_bid, bid, entry)
    pnl, peak_pnl = (bid / entry - 1) * 100, (peak / entry - 1) * 100
    held = (now - datetime.fromisoformat(opened_at)).total_seconds() / 86400
    dte = (date.fromisoformat(expiry) - now.date()).days
    flags = []
    if peak_pnl >= GAVE_BACK_PEAK_PCT and pnl <= peak_pnl * (1 - GAVE_BACK_FRACTION):
        flags.append("gave_back")
    if kind in ("swing", "flow"):
        if held >= NEVER_WORKED_DAYS and pnl <= NEVER_WORKED_LOSS_PCT and peak_pnl < NEVER_WORKED_PEAK_PCT:
            flags.append("never_worked")
        if dte <= LATE_DTE and pnl < 0:
            flags.append("late_and_losing")
    return {"verdict": "CONSIDER_EXIT" if flags else "HOLD", "flags": flags, "pnl_pct": round(pnl, 1), "peak_pnl_pct": round(peak_pnl, 1),
            "held_days": round(held, 1), "dte": dte, "bid": bid, "at": now.isoformat()}


def scorecard(calls: list[dict[str, Any]]) -> dict[str, Any]:
    """Each call is compared with how its trade really ended. A positive benefit means exiting at the call beat the real exit,
    in points of the entry premium (so +10 means 10% of the premium paid was saved)."""
    rules = []
    for rule, text in RULES.items():
        mine = [c for c in calls if c["rule"] == rule]
        done = [c for c in mine if c["exit_price"] is not None]
        gains = [(c["bid"] - c["exit_price"]) / c["entry_price"] * 100 for c in done]
        n = len(gains)
        row: dict[str, Any] = {"rule": rule, "text": text, "calls": len(mine), "scored": n, "verdict": "too_few"}
        if n:
            avg = sum(gains) / n
            row.update({"avg_benefit_pts": round(avg, 1), "earlier_was_better_pct": round(sum(g > 0 for g in gains) / n * 100, 1)})
            if n >= MIN_SCORED:
                row["verdict"] = "earlier_helped" if avg >= CLEAR_PTS else "earlier_hurt" if avg <= -CLEAR_PTS else "no_clear_difference"
        rules.append(row)
    return {"rules": rules, "min_scored": MIN_SCORED, "total_calls": len(calls),
            "note": ("A call is scored once its trade closes by the normal rule: the value of exiting at the call, minus what the real exit got, "
                     "as a share of the premium paid. Calls on the same trade at different times, and trades on the same day, are not independent, "
                     "so the real sample is smaller than the count. Nothing here changes an exit.")}


def label_for(lane: str, labels: dict[str, str]) -> Optional[str]:
    return labels.get(lane)
