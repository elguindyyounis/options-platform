"""One list of every simulated trade the platform has taken, whichever account or research lane took it.

The long-term options account, the five options lanes, the 10x challenge, the swing share lane and the short-term
share lane each keep their own ledger. This puts them in one shape so the Trades page can filter by lane and by
instrument (options or shares) and sort across all of them. It only reads; nothing here places or changes a trade.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from .contracts import contract_label, parse_occ

MAX_PER_SOURCE = 300


def _seconds(a: Optional[str], b: Optional[str]) -> Optional[int]:
    if not a or not b:
        return None
    try:
        return int((datetime.fromisoformat(b) - datetime.fromisoformat(a)).total_seconds())
    except ValueError:
        return None


def _main_rows(manager: Any) -> list[dict[str, Any]]:
    from .trades import build_trades

    rows = []
    for t in build_trades(manager, MAX_PER_SOURCE)["trades"]:
        label = contract_label(t["symbol"], t["right"], t["strike"], t["expiry"])
        rows.append({
            "key": "main:" + t["id"], "id": t["id"], "source": "main", "source_label": "Options account", "horizon": "Long-term",
            "instrument": "options", "symbol": t["symbol"], "label": label, "right": t["right"], "strike": t["strike"], "expiry": t["expiry"],
            "quantity": t["quantity"], "entry_price": t["entry_price"], "exit_price": t["exit_price"], "mark": t["mark"],
            "pnl": t["pnl"], "pnl_pct": t["pnl_pct"], "status": t["status"], "opened_at": t["entry_time"], "closed_at": t["exit_time"],
            "held_seconds": t["held_seconds"], "exit_reason": t["exit_reason"], "has_file": True, "detail": None,
        })
    return rows


def _lane_rows(rep: dict[str, Any], source: str, source_label: str, horizon: str, instrument: str) -> list[dict[str, Any]]:
    rows = []
    for t in rep["trades"][:MAX_PER_SOURCE]:
        closed = t["status"] == "CLOSED"
        info = parse_occ(t.get("contract")) if instrument == "options" else None
        why = t.get("why_entered") or {}
        if instrument == "options":
            right = (info or {}).get("right") or why.get("right")
            strike = (info or {}).get("strike", why.get("strike"))
            expiry = (info or {}).get("expiry") or why.get("expiry")
            label = contract_label(t["symbol"], right, strike, expiry) if right and strike is not None and expiry else (t.get("contract") or t["symbol"])
        else:
            right = strike = expiry = None
            label = t["symbol"]
        rows.append({
            "key": f"{source}:{t['id']}", "id": str(t["id"]), "source": source, "source_label": source_label, "horizon": horizon,
            "instrument": instrument, "symbol": t["symbol"], "label": label, "right": right, "strike": strike, "expiry": expiry,
            "quantity": t["quantity"], "entry_price": t["entry_price"], "exit_price": t["exit_price"],
            "mark": None if closed else t.get("mark_bid"),
            "pnl": t["pnl"] if closed else t.get("unrealized_pnl"),
            "pnl_pct": t["pnl_pct"] if closed else t.get("unrealized_pnl_pct"),
            "status": t["status"], "opened_at": t["opened_at"], "closed_at": t["closed_at"],
            "held_seconds": _seconds(t["opened_at"], t["closed_at"]), "exit_reason": t.get("close_reason"),
            "exit_text": t.get("close_text"), "has_file": False, "detail": t,
        })
    return rows


def build_all(manager: Any, store: Any, fictional: bool, now: datetime, option_lanes: Any) -> dict[str, Any]:
    from . import swing as sw_mod
    from . import shortterm as st_mod

    rows = _main_rows(manager)
    ops = option_lanes.reports(now)
    horizon = {"short": "Short-term", "swing": "Swing", "flow": "Flow"}
    for lane in ops["lanes"]:
        rows += _lane_rows(lane, lane["lane"], lane["label"], horizon.get(lane["kind"], "Lane"), "options")
    rows += _lane_rows(option_lanes.challenge.report(now), "challenge-10x", "10x challenge", "Challenge", "options")
    rows += _lane_rows(sw_mod.build_report(store, fictional, now), sw_mod.LANE, "Swing, shares", "Swing", "shares")
    rows += _lane_rows(st_mod.build_report(store, fictional, now), st_mod.LANE, "Short-term, shares", "Short-term", "shares")
    rows.sort(key=lambda r: r["opened_at"] or "", reverse=True)

    def summarise(sel: list[dict[str, Any]]) -> dict[str, Any]:
        done = [r for r in sel if r["status"] == "CLOSED" and r["pnl"] is not None]
        wins = [r for r in done if r["pnl"] > 0]
        return {"total": len(sel), "open": sum(1 for r in sel if r["status"] != "CLOSED"), "closed": len(done), "wins": len(wins),
                "win_rate_pct": round(len(wins) / len(done) * 100, 1) if done else None,
                "realized_pnl": round(sum(r["pnl"] for r in done), 2),
                "open_pnl": round(sum(r["pnl"] or 0.0 for r in sel if r["status"] != "CLOSED"), 2)}

    sources: dict[str, dict[str, Any]] = {}
    for r in rows:
        sources.setdefault(r["source"], {"source": r["source"], "label": r["source_label"], "instrument": r["instrument"]})
    for s in sources.values():
        s.update(summarise([r for r in rows if r["source"] == s["source"]]))
    return {
        "fictional": fictional, "as_of": now.isoformat(), "trades": rows,
        "summary": {"all": summarise(rows), "options": summarise([r for r in rows if r["instrument"] == "options"]),
                    "shares": summarise([r for r in rows if r["instrument"] == "shares"])},
        "sources": list(sources.values()),
        "caveat": "Simulated fills. Lane and challenge trades are research experiments kept apart from the options account. "
                  "Small samples, and especially fictional data, prove nothing.",
    }
