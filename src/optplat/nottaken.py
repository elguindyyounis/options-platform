"""Display only: entries the engine looked at and did NOT take, counted by reason (UX-12).

Reads the decision journal's ENTRY lines. The journal writes a candidate at most once an hour and a few per name per
cycle, so every count is a lower bound ("at least"). Only lines of the same data kind (demo or real) as the page count.
Nothing here places, changes or blocks an order.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

# disposition -> plain-language reason. Only dispositions the engine really writes for an entry that was not taken.
REASONS = {
    "SKIPPED_REGIME": "market-regime guard held it back",
    "SKIPPED_HELD": "already holding that name",
    "SKIPPED_COOLDOWN": "in cooldown after a recent trade",
    "NOT_CHOSEN": "a stronger candidate was taken first",
    "NOT_CHOSEN_SIZE_CAP": "did not fit the size cap",
    "NOT_CHOSEN_COMMITTEE": "the committee did not back it",
}


def not_taken(store: Any, now: datetime, *, fictional: bool, hours: int = 24) -> dict[str, Any]:
    since = now - timedelta(hours=hours)
    counts: dict[str, int] = {}
    latest = None
    for d in store.list_decisions(kind="ENTRY", include_fictional=bool(fictional), limit=100_000):
        if d["disposition"] not in REASONS or bool(d["fictional"]) != bool(fictional):
            continue
        if datetime.fromisoformat(d["ts"]) < since:
            continue
        counts[d["disposition"]] = counts.get(d["disposition"], 0) + 1
        latest = latest or d["ts"]  # newest first
    reasons = [{"disposition": k, "reason": REASONS[k], "count": counts[k]} for k in sorted(counts, key=lambda k: -counts[k])]
    return {"hours": hours, "total": sum(counts.values()), "reasons": reasons, "latest": latest,
            "lower_bound": True, "fictional": bool(fictional)}
