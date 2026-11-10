"""What happened to the candidates the platform did not take, and to the ones it did.

The engine writes one append-only record per decision (see ``TradingEngine._journal``). This module turns
those records into measurements: for each entry candidate, what the contract's bid was some hours or days
later, taken only from recorded snapshots that passed the data-quality gate. A missing or unusable later
quote is UNOBSERVABLE, never estimated. Results for a group are marked descriptive until it has at least
``MIN_SAMPLE`` matured candidates. Nothing here says a filter or strategy works.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Optional, Sequence

from .dataquality import check_snapshot
from .marketdata import snapshot_from_dict
from .models import OptionContract
from .store import Store

HORIZONS_HOURS = (4, 24, 120)
MIN_SAMPLE = 30
GAP_TOLERANCE = 0.25  # the later snapshot must be within 25% of the horizon (at least 1 hour) after the target time

PENDING, UNOBSERVABLE, OK = "PENDING", "UNOBSERVABLE", "OK"


def forward_return(store: Store, decision: dict[str, Any], horizon_h: float, now: datetime) -> tuple[str, Optional[float]]:
    """Percent change from the candidate's reference price to the contract's bid `horizon_h` hours later."""
    ref = decision.get("ref_price")
    if not ref or ref <= 0:
        return UNOBSERVABLE, None
    target = datetime.fromisoformat(decision["ts"]) + timedelta(hours=horizon_h)
    if now < target:
        return PENDING, None
    row = store.first_snapshot_at_or_after(decision["symbol"], target, include_fictional=decision["fictional"])
    if row is None:
        return PENDING, None  # nothing recorded that late yet
    at = datetime.fromisoformat(row["recorded_at"])
    if at - target > timedelta(hours=max(1.0, horizon_h * GAP_TOLERANCE)):
        return UNOBSERVABLE, None  # a gap (overnight, weekend, outage): do not stretch an old reading across it
    checked = check_snapshot(snapshot_from_dict(row["payload"]), at)
    if checked.snapshot is None:
        return UNOBSERVABLE, None
    contract = OptionContract.from_dict(decision["payload"]["contract"])
    for r in checked.snapshot.rows:
        if r.contract == contract:
            return OK, round((r.bid - ref) / ref * 100, 2)
    return UNOBSERVABLE, None


def journal_summary(
    store: Store, now: datetime, horizons: Sequence[float] = HORIZONS_HOURS, include_fictional: bool = False
) -> dict[str, Any]:
    decisions = store.list_decisions(include_fictional=include_fictional, newest_first=False, limit=100_000)
    by_disposition: dict[str, int] = {}
    forward: dict[str, dict[str, Any]] = {}
    for d in decisions:
        by_disposition[f"{d['kind']}:{d['disposition']}"] = by_disposition.get(f"{d['kind']}:{d['disposition']}", 0) + 1
        if d["kind"] != "ENTRY":
            continue
        group = forward.setdefault(d["disposition"], {"candidates": 0})
        group["candidates"] += 1
        for h in horizons:
            status, value = forward_return(store, d, h, now)
            cell = group.setdefault(f"{h:g}h", {"matured": 0, "pending": 0, "unobservable": 0, "returns": []})
            if status == OK:
                cell["matured"] += 1
                cell["returns"].append(value)
            elif status == PENDING:
                cell["pending"] += 1
            else:
                cell["unobservable"] += 1
    for group in forward.values():
        for key, cell in list(group.items()):
            if key == "candidates":
                continue
            rets = cell.pop("returns")
            cell["mean_return_pct"] = round(sum(rets) / len(rets), 2) if rets else None
            cell["descriptive_only"] = cell["matured"] < MIN_SAMPLE
    return {
        "decisions": len(decisions),
        "by_disposition": dict(sorted(by_disposition.items())),
        "horizons_hours": list(horizons),
        "forward_return_by_disposition": forward,
        "min_sample": MIN_SAMPLE,
        "caveat": (
            "Forward return is the contract's bid at the horizon versus the candidate's reference price, from "
            "recorded delayed data. Groups under the minimum sample are descriptive only. Candidates overlap in "
            "time and are not independent trades."
        ),
    }
