"""The options tracker: what happened to unusual option contracts after the scanner flagged them.

The scanner flags a contract on a day (volume far above open interest, and so on). This module watches what that
contract did afterwards. On each later scan it reads the contract's quote again and, for the 1, 3 and 7 trading day
marks, records two things:

* the contract's return if someone had bought at the ask when it was flagged and sold at the bid at the mark
  (so the spread is already paid: most flagged contracts are expected to lose on this measure), and
* how far the underlying moved, in the direction that would have helped the contract.

Marks are grouped by what was known when the flag was raised (volume to open interest ratio, fresh or established
open interest, the inferred side of the trade, days to expiry, liquidity tier, sector, call or put) so the dashboard
can show which features, if any, came before a better outcome than the average flagged contract. Groups with fewer
than MIN_N marks are shown but labelled too small to read. Nothing here places an order or changes a threshold.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from statistics import median
from typing import Any, Optional

from .market_clock import HOLIDAYS
from .marketdata import MarketSnapshot
from .models import Right

HORIZONS = (1, 3, 7)     # trading days after the flag
SLACK = 2                # a mark may be taken up to this many trading days late (a missed scan), never early
MIN_N = 20               # marks a group needs before the dashboard calls a difference a finding
WATCH_DAYS = 12          # calendar days a flagged contract stays on the watch list


def _is_trading_day(d: date) -> bool:
    return d.weekday() < 5 and d not in HOLIDAYS.get(d.year, frozenset())


def trading_days_between(a: date, b: date) -> int:
    """Trading days after a, up to and including b. Zero when b is not after a."""
    n, d = 0, a
    while d < b:
        d += timedelta(days=1)
        if _is_trading_day(d):
            n += 1
    return n


def horizons_due(age: int, done: set[int]) -> list[int]:
    """Which marks this observation can fill: the age must have reached the horizon, but not by more than SLACK."""
    return [h for h in HORIZONS if h not in done and h <= age <= h + SLACK]


def _bucket_ratio(s: dict[str, Any]) -> str:
    r = s.get("volume_oi_ratio")
    if r is None:
        return "No ratio (open interest zero or missing)"
    return "3 to 5 times" if r < 5 else "5 to 10 times" if r < 10 else "10 to 25 times" if r < 25 else "25 times or more"


def _bucket_dte(s: dict[str, Any]) -> str:
    d = s.get("dte")
    if d is None:
        return "Unknown"
    return "7 days or less" if d <= 7 else "8 to 30 days" if d <= 30 else "31 to 90 days" if d <= 90 else "Over 90 days"


FEATURES: dict[str, tuple[str, Any]] = {
    "ratio": ("Volume against open interest", _bucket_ratio),
    "oi": ("Open interest before the flag", lambda s: "Fresh (under 10)" if s.get("low_oi") else "Established"),
    "side": ("Inferred side of the last trade", lambda s: {"BUY": "Looks like buying", "SELL": "Looks like selling"}.get(s.get("likely_side"), "Unclear")),
    "dte": ("Days to expiry", _bucket_dte),
    "tier": ("Liquidity grade", lambda s: "Grade " + str(s.get("liquidity_tier") or "?")),
    "right": ("Call or put", lambda s: "Call" if s.get("right") == "C" else "Put"),
    "sector": ("Sector", lambda s: s.get("sector") or "Other"),
}


def features_of(sighting: dict[str, Any]) -> dict[str, str]:
    return {k: fn(sighting) for k, (_, fn) in FEATURES.items()}


def make_mark(sighting: dict[str, Any], snap: MarketSnapshot, row: Any, day: date, horizon: int, age: int, oi_verdict: str) -> Optional[dict[str, Any]]:
    entry, bid = sighting.get("ask"), row.bid
    then, now_px = sighting.get("underlying_price"), snap.underlying
    if not entry or entry <= 0 or bid is None or bid < 0 or not then or then <= 0 or now_px <= 0:
        return None
    move = (now_px / then - 1) * 100
    sign = 1 if sighting.get("right") == Right.CALL.value else -1
    return {"contract": sighting["contract"], "symbol": sighting["symbol"], "sighted_day": sighting["day"], "observed_day": day.isoformat(),
            "horizon": horizon, "age_days": age, "entry_ask": entry, "exit_bid": bid, "ret_pct": round((bid / entry - 1) * 100, 2),
            "underlying_then": then, "underlying_now": now_px, "move_pct": round(move, 2), "helpful_move_pct": round(move * sign, 2),
            "oi_verdict": oi_verdict, "score": sighting.get("score"), "features": features_of(sighting)}


def observe(store: Any, snap: MarketSnapshot, day: date, fictional: bool, compare: Any) -> int:
    """Take any marks this chain makes possible. ``compare`` is scanner.compare_with_prior. Returns marks recorded."""
    since = (day - timedelta(days=WATCH_DAYS)).isoformat()
    sightings = store.unusual_sightings(snap.symbol, since, day.isoformat(), fictional)
    if not sightings:
        return 0
    by_contract = {r.contract.occ_symbol.strip(): r for r in snap.rows}
    have: dict[tuple[str, str], set[int]] = {}
    for m in store.tracker_marks(fictional):
        have.setdefault((m["contract"], m["sighted_day"]), set()).add(m["horizon"])
    added = 0
    for s in sightings:
        row = by_contract.get(s["contract"])
        if row is None:
            continue
        age = trading_days_between(date.fromisoformat(s["day"]), day)
        for h in horizons_due(age, have.get((s["contract"], s["day"]), set())):
            cmp = compare(s, row.open_interest, day)
            mark = make_mark(s, snap, row, day, h, age, cmp["oi_verdict"])
            if mark and store.record_tracker_mark(s["contract"], s["day"], h, fictional, day.isoformat(), mark):
                added += 1
    return added


# ------------------------------------------------------------------ reading the marks
def _stats(marks: list[dict[str, Any]]) -> dict[str, Any]:
    rets = [m["ret_pct"] for m in marks]
    n = len(rets)
    return {"n": n, "win_rate_pct": round(sum(r > 0 for r in rets) / n * 100, 1) if n else None,
            "avg_ret_pct": round(sum(rets) / n, 2) if n else None, "median_ret_pct": round(median(rets), 2) if n else None,
            "avg_helpful_move_pct": round(sum(m["helpful_move_pct"] for m in marks) / n, 2) if n else None, "enough": n >= MIN_N}


def summarize(marks: list[dict[str, Any]]) -> dict[str, Any]:
    horizons = {str(h): _stats([m for m in marks if m["horizon"] == h]) for h in HORIZONS}
    groups: list[dict[str, Any]] = []
    for h in HORIZONS:
        at = [m for m in marks if m["horizon"] == h]
        base = _stats(at)
        for key, (label, _) in FEATURES.items():
            buckets: dict[str, list[dict[str, Any]]] = {}
            for m in at:
                buckets.setdefault(m["features"].get(key, "Unknown"), []).append(m)
            for name, ms in buckets.items():
                st = _stats(ms)
                diff = None if st["avg_ret_pct"] is None or base["avg_ret_pct"] is None else round(st["avg_ret_pct"] - base["avg_ret_pct"], 2)
                groups.append({"horizon": h, "feature": key, "feature_label": label, "bucket": name, **st, "vs_all_pct": diff})
    confirmed = [m for m in marks if m["horizon"] == 3 and m["oi_verdict"] == "OI_ROSE"]
    other = [m for m in marks if m["horizon"] == 3 and m["oi_verdict"] != "OI_ROSE"]
    return {"horizons": horizons, "groups": groups,
            "findings": findings(groups),
            "oi_check": {"oi_rose": _stats(confirmed), "other": _stats(other)}}


def findings(groups: list[dict[str, Any]]) -> list[str]:
    """Plain sentences, only for groups big enough to read and only when they differ from the average by a margin."""
    out = []
    for g in sorted((g for g in groups if g["enough"] and g["vs_all_pct"] is not None and g["horizon"] == 3), key=lambda g: -abs(g["vs_all_pct"])):
        if abs(g["vs_all_pct"]) < 3.0:
            continue
        word = "better" if g["vs_all_pct"] > 0 else "worse"
        out.append(f"{g['feature_label']}: {g['bucket'].lower()} did {abs(g['vs_all_pct']):.1f} points {word} than the average flagged contract "
                   f"after 3 trading days (average {g['avg_ret_pct']:+.1f}%, {g['n']} marks).")
    return out[:6]


def watching(store: Any, fictional: bool, today: date, limit: int = 40) -> list[dict[str, Any]]:
    """Recent flags and which marks each has so far, newest first."""
    since = (today - timedelta(days=WATCH_DAYS)).isoformat()
    sightings = store.unusual_sightings(None, since, (today + timedelta(days=1)).isoformat(), fictional)
    marks: dict[tuple[str, str], dict[int, dict[str, Any]]] = {}
    for m in store.tracker_marks(fictional):
        marks.setdefault((m["contract"], m["sighted_day"]), {})[m["horizon"]] = m
    out = []
    for s in sorted(sightings, key=lambda x: (x["day"], x.get("score") or 0), reverse=True)[:limit]:
        got = marks.get((s["contract"], s["day"]), {})
        out.append({"contract": s["contract"], "symbol": s["symbol"], "right": s["right"], "strike": s["strike"], "expiry": s["expiry"],
                    "day": s["day"], "score": s.get("score"), "volume": s.get("volume"), "open_interest": s.get("open_interest"),
                    "ratio": s.get("volume_oi_ratio"), "side": s.get("likely_side"), "entry_ask": s.get("ask"),
                    "marks": {str(h): (None if h not in got else {"ret_pct": got[h]["ret_pct"], "helpful_move_pct": got[h]["helpful_move_pct"]}) for h in HORIZONS}})
    return out


def report(store: Any, fictional: bool, now: datetime, day: date, criteria: list[dict[str, Any]]) -> dict[str, Any]:
    marks = store.tracker_marks(fictional)
    return {"fictional": fictional, "as_of": now.isoformat(), "criteria": criteria, "horizons_days": list(HORIZONS), "min_n": MIN_N,
            "total_marks": len(marks), "watching": watching(store, fictional, day), **summarize(marks),
            "method": "A flagged contract is 'bought' at its ask on the flag day and 'sold' at its bid on the mark day, so the spread is already "
                      "paid. 'Helpful move' is the underlying's move in the direction that would help the contract (up for a call, down for a put).",
            "limitations": [
                "Only contracts whose chain was read again on a later scan can be marked; a missed scan, an expired contract or a chain that failed the data-quality gate leaves a gap.",
                f"A group needs {MIN_N} marks before it is called a finding. Marks on the same underlying and day are not independent, so even that is a low bar.",
                "Free delayed quotes. Prices are recorded when the scanner ran, not at the close.",
                "A feature that did better here is a lead to test next, not proof of an edge. Nothing in this table feeds a trade except as noted on the Agents page.",
            ]}
