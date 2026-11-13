"""Where trading activity is moving between sectors, day by day, from the scans the platform already stores.

For each trading day the newest scan that finished is used. A sector's share is its dollar volume as a percentage of
all the ranked names' dollar volume that day. A share that rises over several days means trading is concentrating
there; one that falls means it is thinning out. That is a description of activity in a fixed 200-name list, not a
measurement of money entering or leaving a sector, and it cannot say why. Price moves are the average change of the
sector's ranked names, compounded across the days shown.
"""
from __future__ import annotations

from typing import Any, Optional

MIN_DAYS = 2
MAX_DAYS = 20
TREND_PTS = 0.5     # a change in share smaller than this many percentage points is called steady


def by_day(scans: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The newest usable scan per session day, oldest first. A scan without a heat map is skipped."""
    days: dict[str, dict[str, Any]] = {}
    for s in scans:
        if s.get("heat_map") and s.get("heat_map", {}).get("sectors") and s.get("session_day"):
            days[s["session_day"]] = s
    return [days[d] for d in sorted(days)][-MAX_DAYS:]


def build(scans: list[dict[str, Any]], fictional: bool) -> dict[str, Any]:
    daily = by_day(scans)
    out: dict[str, Any] = {"fictional": fictional, "days": [s["session_day"] for s in daily], "sectors": [], "summary": [], "ready": len(daily) >= MIN_DAYS,
                           "caveat": "Share of dollar volume across about 200 fixed names, from free daily bars. It shows where trading is concentrating, "
                                     "not where money is coming from, and it cannot say why."}
    if not daily:
        return out
    series: dict[str, list[Optional[dict[str, float]]]] = {}
    calls: dict[str, tuple[float, float]] = {}
    for i, s in enumerate(daily):
        total = sum(x["dollar_volume"] for x in s["heat_map"]["sectors"]) or 0
        seen = set()
        for x in s["heat_map"]["sectors"]:
            row = series.setdefault(x["sector"], [None] * len(daily))
            row[i] = {"share_pct": round(x["dollar_volume"] / total * 100, 2) if total else 0.0, "avg_change_pct": x["avg_change_pct"],
                      "relative_volume": x.get("avg_relative_volume")}
            seen.add(x["sector"])
    last = daily[-1]
    for n in last.get("option_names", []):
        sec = n.get("sector") or "Other"
        c, p = calls.get(sec, (0.0, 0.0))
        calls[sec] = (c + (n.get("call_volume") or 0), p + (n.get("put_volume") or 0))
    for sec, row in series.items():
        pts = [r for r in row if r]
        if not pts:
            continue
        first, latest = pts[0], pts[-1]
        prev = pts[-2] if len(pts) > 1 else None
        cum = 1.0
        for r in pts:
            cum *= 1 + r["avg_change_pct"] / 100
        c, p = calls.get(sec, (0.0, 0.0))
        out["sectors"].append({
            "sector": sec, "days_seen": len(pts), "share_pct": latest["share_pct"],
            "share_change_pts": round(latest["share_pct"] - first["share_pct"], 2),
            "share_change_1d_pts": None if prev is None else round(latest["share_pct"] - prev["share_pct"], 2),
            "avg_change_pct": latest["avg_change_pct"], "cumulative_change_pct": round((cum - 1) * 100, 2),
            "relative_volume": latest["relative_volume"], "call_put_ratio": round(c / p, 2) if p > 0 else None,
            "history": [None if r is None else r["share_pct"] for r in row],
            "trend": "STEADY" if abs(latest["share_pct"] - first["share_pct"]) < TREND_PTS else ("GAINING" if latest["share_pct"] > first["share_pct"] else "LOSING"),
        })
    out["sectors"].sort(key=lambda x: -x["share_change_pts"])
    if out["ready"]:
        gain = [x for x in out["sectors"] if x["trend"] == "GAINING"][:3]
        lose = [x for x in reversed(out["sectors"]) if x["trend"] == "LOSING"][:3]
        span = f"{out['days'][0]} to {out['days'][-1]}"
        if gain:
            out["summary"].append("Trading is concentrating in " + ", ".join(f"{x['sector']} ({x['share_change_pts']:+.1f} points)" for x in gain) + f" ({span}).")
        if lose:
            out["summary"].append("Trading is thinning out in " + ", ".join(f"{x['sector']} ({x['share_change_pts']:+.1f} points)" for x in lose) + ".")
        if not gain and not lose:
            out["summary"].append(f"Sector shares of trading have been steady ({span}).")
    else:
        out["summary"].append(f"Rotation needs scans from at least {MIN_DAYS} different trading days; {len(daily)} so far. It fills in as the scanner runs each day.")
    return out
