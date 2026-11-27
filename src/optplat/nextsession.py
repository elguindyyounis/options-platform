"""What the research lanes would do at the next session, worked out while the market is closed. PREVIEW ONLY.

The swing lanes decide on the newest completed daily bar, so once a session has closed their next entries and exits
are already fixed by data that exists. This module replays those decisions WITHOUT side effects: it never opens or
closes a trade, never writes a lane's "bar already judged" key, and never places an order. The lanes themselves
re-check everything at the open with fresh quotes, so prices and sizes here are last quotes, not promises.

Lanes that decide during the session (EMA9/VWAP short-term lanes, the challenge account, the flow lane and the main
account) cannot be previewed honestly; they are listed with when and how they decide instead.
"""
from __future__ import annotations

import json
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Optional

from . import optionlanes as ol
from . import shortterm as st_mod
from . import swing as sw_mod
from .dataquality import check_snapshot
from .market_clock import CLOSE, EARLY_CLOSE, EARLY_CLOSES, HOLIDAYS, NY, OPEN, session_status
from .models import Right
from .scanner import SECTOR_OF

STATE_KEY = "next_session_plan"
BUILD_AFTER_CLOSE = timedelta(minutes=20)       # let the provider publish the final daily bar first
PREVIEW_MAX_QUOTE_AGE_S = 4 * 24 * 3600         # quotes after a long weekend are old; they are labelled, not trusted
VERSION = "next-session-v1"


def next_session(now: datetime) -> Optional[dict[str, Any]]:
    """The next regular session that has not started yet, from the hand-kept calendar. None when the table runs out."""
    local = now.astimezone(NY)
    closed: list[str] = []
    for k in range(0, 15):
        d = local.date() + timedelta(days=k)
        if d.year not in HOLIDAYS:
            return None
        if d.weekday() >= 5 or d in HOLIDAYS[d.year]:
            if k:
                closed.append(d.isoformat())
            continue
        if k == 0 and local.time() >= OPEN:
            continue                                    # today's session has started or finished
        early = d in EARLY_CLOSES.get(d.year, frozenset())
        opens = datetime.combine(d, OPEN, NY)
        closes = datetime.combine(d, EARLY_CLOSE if early else CLOSE, NY)
        return {"date": d.isoformat(), "opens_at": opens.astimezone(timezone.utc).isoformat(),
                "closes_at": closes.astimezone(timezone.utc).isoformat(), "early_close": early, "closed_days_before": closed}
    return None


def last_close(now: datetime) -> Optional[datetime]:
    """When the most recent session closed, or None while a session is open or the calendar runs out."""
    if session_status(now)[0]:
        return None
    local = now.astimezone(NY)
    for k in range(0, 15):
        d = local.date() - timedelta(days=k)
        if d.year not in HOLIDAYS:
            return None
        if d.weekday() >= 5 or d in HOLIDAYS[d.year]:
            continue
        closes = datetime.combine(d, EARLY_CLOSE if d in EARLY_CLOSES.get(d.year, frozenset()) else CLOSE, NY)
        if closes <= local:
            return closes.astimezone(timezone.utc)
    return None


def _saved_mark(store: Any, trade_id: int) -> Optional[tuple[float, float, str]]:
    try:
        m = json.loads(store.get_state(f"lane_mark:{trade_id}", "") or "{}")
        return (float(m["bid"]), float(m["ask"]), str(m.get("at", ""))) if m else None
    except (ValueError, KeyError, TypeError):
        return None


def _held_exit(lane: ol.OptionLane, t: dict[str, Any], r: Optional[dict[str, Any]], session: date) -> dict[str, Any]:
    """The same exit rules as OptionLane._long_exit, judged on saved marks and the newest completed bar."""
    o, p = t["open_payload"], lane.p
    mark = _saved_mark(lane.store, t["id"])
    entry = t["entry_price"]
    stop_bid, target_bid = round(entry * (1 - o["stop_pct"] / 100), 4), round(entry * (1 + o["target_pct"] / 100), 4)
    row = {"symbol": t["symbol"], "contract": o["contract"], "right": o["right"], "quantity": t["quantity"], "entry": entry,
           "last_bid": mark[0] if mark else None, "mark_at": mark[2] if mark else None,
           "stop_bid": stop_bid, "target_bid": target_bid, "expiry": o["expiry"]}
    reason = None
    if mark and mark[0] <= stop_bid:
        reason = "stop"
    elif mark and mark[0] >= target_bid:
        reason = "target"
    elif (date.fromisoformat(o["expiry"]) - session).days <= 2:
        reason = "expiry_near"
    elif r is not None and ((o["right"] == "C" and r["close"] < r["sma_slow"]) or (o["right"] == "P" and r["close"] > r["sma_slow"])):
        reason = "trend_break"
    elif r is not None:
        opened_day = o.get("bar_day") or datetime.fromisoformat(t["opened_at"]).date().isoformat()
        held_bars = sum(1 for d in r["days"] if d.isoformat() > opened_day)
        limit = o.get("max_hold_bars", p.max_hold_bars)
        row["bars_held"], row["bar_limit"] = held_bars, limit
        if held_bars >= limit:
            reason = "time"
    row["action"] = "WOULD_SELL" if reason else "HOLD"
    row["reason"] = reason or ("no daily bar to judge the trend or holding time" if r is None else None)
    if reason and mark is None:
        row["note"] = "no saved quote: the lane sells only once it has a usable bid"
    return row


def _swing_option_lane(lane: ol.OptionLane, now: datetime, session: dict[str, Any]) -> dict[str, Any]:
    p = lane.p
    sess_day = date.fromisoformat(session["date"])
    sess_open = datetime.fromisoformat(session["opens_at"])
    out: dict[str, Any] = {"lane": p.lane, "label": p.label, "kind": p.kind, "previewable": True,
                           "buys": [], "queued": [], "sells": [], "holds": [], "blocked": [], "errors": [],
                           "max_entries": ol.MAX_ENTRIES_PER_STEP}
    held = lane._held()
    try:
        raw = lane.feed.daily(p.symbols, sw_mod.BARS_MONTHS)
    except Exception as exc:  # noqa: BLE001 - no data means no preview, and it is shown
        out["errors"].append(f"daily bars unavailable: {type(exc).__name__}: {str(exc)[:100]}")
        return out
    reads = {s: sw_mod.read(raw.get(s, []), now) for s in p.symbols}
    out["bar_day"] = max((r["day"] for r in reads.values() if r), default=None)
    out["bar_day"] = out["bar_day"].isoformat() if out["bar_day"] else None
    for t in held:
        row = _held_exit(lane, t, reads.get(t["symbol"]), sess_day)
        (out["sells"] if row["action"] == "WOULD_SELL" else out["holds"]).append(row)
    remaining = [t for t in held if not any(s["contract"] == t["open_payload"]["contract"] for s in out["sells"])]
    marks = {t["open_payload"]["contract"]: (m[0], m[1]) for t in remaining if (m := _saved_mark(lane.store, t["id"]))}
    signals = []
    for sym in p.symbols:
        r = reads.get(sym)
        if r is None or lane.store.get_state(f"optlane_bar:{p.lane}:{sym}", "") == r["day"].isoformat():
            continue                                    # no bar, or this bar was already judged in a session
        right = ol.swing_signal(r, p)
        if right:
            signals.append((r["rsi_dip"] if right == "C" else -r["rsi_peak"], sym, right, r))
    signals.sort(key=lambda x: (x[0], x[1]))
    entries = reads_done = 0
    for _, sym, right, r in signals:
        base = {"symbol": sym, "right": right, "signal_bar": r["day"].isoformat(), "close": round(r["close"], 4),
                "rsi": round(r["rsi"], 1), "sma_slow": round(r["sma_slow"], 4)}

        def block(why: str) -> None:
            out["blocked"].append({**base, "reason": why})

        if entries >= ol.MAX_ENTRIES_PER_STEP:
            block(f"after the lane's {ol.MAX_ENTRIES_PER_STEP} entries for this bar")
            continue
        if reads_done >= ol.MAX_CHAIN_READS_PER_STEP:
            block(f"after the lane's {ol.MAX_CHAIN_READS_PER_STEP} option-chain reads for this bar")
            continue
        if not lane._may_open(sym, remaining, marks):
            block("book full: open positions, sector share or stacking limit")
            continue
        state = lane._earnings_state(sym, sess_day)
        if p.earnings_gate and state not in ("FUND", "CLEAR"):
            block(f"earnings {state.lower()}: this lane needs a clear calendar")
            continue
        try:
            ok, why, _ = lane.feed.regime.allows(right)
        except Exception:  # noqa: BLE001 - the lane itself treats an unknown regime as allowed; say so
            ok, why = True, ""
        if not ok:
            block(why or "market-regime guard")
            continue
        reads_done += 1
        base["rank"] = reads_done                       # the order the lane will try it at the open
        try:
            snap = lane.feed.window(sym, p.dte_min, p.dte_max, 3)
            chk = check_snapshot(snap, max(now, lane.clock()), max_age_s=PREVIEW_MAX_QUOTE_AGE_S)
            why_not = None if chk.snapshot is not None else (chk.issues[-1].kind if chk.issues else "unknown")
        except Exception as exc:  # noqa: BLE001
            chk, why_not = None, type(exc).__name__
        if why_not is not None:
            # Off-hours chains are often stale or empty; the lane reads them again at the open. Queued, not refused.
            out["queued"].append({**base, "earnings_state": state, "why_no_contract_yet": why_not})
            continue
        snapx = chk.snapshot
        if snapx.source.startswith(("ibkr", "yahoo-fallback")) and not snapx.timestamp_verified:
            # pick_contract refuses these by design; say so instead of blaming the lane's quote limits
            block("IBKR quote time not verified: lanes do not open on unverified IBKR chains (owner decision pending)")
            continue
        row = ol.pick_contract(snapx, Right(right), sess_open, p)
        if row is None:
            block("no contract met the expiry, spread and open-interest limits on the last quotes")
            continue
        qty = int(p.budget_usd // (row.ask * ol.MULTIPLIER))
        if qty < 1:
            block(f"one contract costs more than the ${p.budget_usd:,.0f} budget")
            continue
        entries += 1
        pick = {**base, "contract": row.contract.occ_symbol.strip(), "expiry": row.contract.expiry.isoformat(),
                "strike": row.contract.strike, "bid": row.bid, "ask": row.ask,
                "spread_pct": round((row.ask - row.bid) / row.ask * 100, 1), "quantity": qty,
                "premium_usd": round(qty * row.ask * ol.MULTIPLIER, 2), "earnings_state": state,
                "size_vs_volume_pct": round(qty / row.volume * 100, 1) if row.volume else None,
                "size_vs_oi_pct": round(qty / row.open_interest * 100, 1) if row.open_interest else None,
                "quote_as_of": chk.snapshot.as_of.isoformat()}
        out["buys"].append(pick)
        remaining.append({"symbol": sym, "open_payload": {"contract": pick["contract"]}, "entry_price": row.ask})
    return out


def _swing_share_lane(store: Any, provider: Any, calendar: Any, now: datetime, session: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {"lane": sw_mod.LANE, "label": "Swing pullback (shares)", "kind": "swing", "previewable": True,
                           "buys": [], "sells": [], "holds": [], "blocked": [], "errors": []}
    try:
        raw = provider.daily_bars(sw_mod.SYMBOLS, months=sw_mod.BARS_MONTHS)
    except Exception as exc:  # noqa: BLE001
        out["errors"].append(f"daily bars unavailable: {type(exc).__name__}: {str(exc)[:100]}")
        return out
    reads = {s: sw_mod.read(raw.get(s, []), now) for s in sw_mod.SYMBOLS}
    open_by = {t["symbol"]: t for t in store.lane_trades(sw_mod.LANE, provider.fictional, 2000) if t["closed_at"] is None}
    for sym, t in list(open_by.items()):
        r = reads.get(sym)
        why = sw_mod.exit_reason(t, r) if r else None
        row = {"symbol": sym, "quantity": t["quantity"], "entry": t["entry_price"], "last_close": round(r["close"], 4) if r else None,
               "stop": t["open_payload"].get("stop"), "target": t["open_payload"].get("target"), "reason": why}
        if why:
            out["sells"].append({**row, "action": "WOULD_SELL"})
            open_by.pop(sym)
        else:
            out["holds"].append({**row, "action": "HOLD"})
    lane = sw_mod.SwingLane(provider, store, clock=lambda: now, calendar=calendar)
    for sym in sw_mod.SYMBOLS:
        r = reads.get(sym)
        if r is None or sym in open_by or store.get_state(f"swing_last_bar:{sym}", "") == r["day"].isoformat():
            continue
        if not sw_mod.entry_signal(r):
            continue
        base = {"symbol": sym, "right": "SHARES", "signal_bar": r["day"].isoformat(), "close": round(r["close"], 4)}
        sector = SECTOR_OF.get(sym, sym)
        if len(open_by) >= sw_mod.MAX_OPEN or sum(1 for s in open_by if SECTOR_OF.get(s, s) == sector) >= sw_mod.MAX_PER_SECTOR:
            out["blocked"].append({**base, "reason": "book full: open positions or sector share"})
            continue
        if not lane._earnings_ok(sym, date.fromisoformat(session["date"])):
            out["blocked"].append({**base, "reason": "earnings soon or unknown"})
            continue
        px = round(r["close"] * (1 + sw_mod.SLIPPAGE_PCT / 100), 4)
        qty = int(sw_mod.NOTIONAL_USD // px)
        if qty < 1:
            continue
        out["buys"].append({**base, "quantity": qty, "price": px, "notional_usd": round(qty * px, 2)})
        open_by[sym] = {"symbol": sym}
    return out


def build_plan(engine: Any, now: Optional[datetime] = None) -> dict[str, Any]:
    """The whole preview. Reads data; writes nothing except the plan itself (see ``refresh``)."""
    now = now or engine.clock()
    session = next_session(now)
    plan: dict[str, Any] = {"version": VERSION, "built_at": now.isoformat(), "fictional": engine.provider.fictional,
                            "next_session": session, "lanes": [], "decided_in_session": [],
                            "places_orders": False,
                            "note": ("Worked out from the newest completed daily bar and the last saved quotes. The lanes "
                                     "re-check everything at the open, so prices and sizes can change and an entry can "
                                     "still be refused.")}
    if session is None:
        plan["status"] = "NO_CALENDAR"
        return plan
    cfg = engine.config()
    if cfg.option_lanes_enabled:
        for lane in engine.option_lanes.lanes:
            if lane.p.kind == "swing":
                try:
                    plan["lanes"].append(_swing_option_lane(lane, now, session))
                except Exception as exc:  # noqa: BLE001 - one lane's failure must not hide the others
                    plan["lanes"].append({"lane": lane.p.lane, "label": lane.p.label, "errors": [f"{type(exc).__name__}: {str(exc)[:120]}"]})
            elif lane.p.kind == "short":
                plan["decided_in_session"].append({"lane": lane.p.lane, "label": lane.p.label,
                    "when": f"{st_mod.ENTRY_FROM:%H:%M}-{st_mod.ENTRY_UNTIL:%H:%M} New York time, on 5-minute EMA9/VWAP crosses; flat by {st_mod.FLAT_BY:%H:%M}"})
            elif lane.p.kind == "flow":
                plan["decided_in_session"].append({"lane": lane.p.lane, "label": lane.p.label,
                    "when": "after the session's first scan, when yesterday's unusual contracts show open interest rose"})
        plan["decided_in_session"].append({"lane": "challenge-10x", "label": "10x challenge",
                                           "when": "during the session, on the short-term signal and its critic"})
    if cfg.swing_enabled:
        try:
            plan["lanes"].append(_swing_share_lane(engine.store, engine.provider, engine.calendar, now, session))
        except Exception as exc:  # noqa: BLE001
            plan["lanes"].append({"lane": sw_mod.LANE, "label": "Swing pullback (shares)", "errors": [f"{type(exc).__name__}: {str(exc)[:120]}"]})
    if cfg.auto_entries:
        plan["decided_in_session"].append({"lane": "main", "label": "Main options account",
                                           "when": "each engine cycle while the market is open, from live chains"})
    plan["status"] = "READY"
    plan["counts"] = {k: sum(len(l.get(k, [])) for l in plan["lanes"]) for k in ("buys", "queued", "sells", "blocked")}
    return plan


SELL_BY_RULE = ("time", "expiry_near", "trend_break")   # fixed by the bar or the calendar, not by the opening bid
TIER_TEXT = {"WILL_SELL": "Will sell", "LIKELY_SELL": "Likely sell", "LIKELY_BUY": "Likely buy",
             "POSSIBLE_BUY": "Possible buy", "WONT": "Won't trade"}


def add_tiers(plan: dict[str, Any]) -> dict[str, Any]:
    """How sure each line is. Sells fixed by the bar or the calendar WILL happen once there is a bid; a premium stop or
    target depends on the opening bid. A buy within the lane's first N tries with a contract already picked is LIKELY;
    one without a usable contract yet, or after the first N, is only POSSIBLE. Blocked signals WON'T trade."""
    tally = {k: 0 for k in TIER_TEXT}
    for lane in plan.get("lanes", []):
        cap = lane.get("max_entries")
        for x in lane.get("sells", []):
            # share-lane exits are judged on the daily close, so they are fixed by the bar too
            x["tier"] = "WILL_SELL" if x.get("reason") in SELL_BY_RULE or lane.get("lane") == sw_mod.LANE else "LIKELY_SELL"
        for x in lane.get("buys", []):
            x["tier"] = "LIKELY_BUY" if cap is None or x.get("rank", 1) <= cap else "POSSIBLE_BUY"
        for x in lane.get("queued", []):
            x["tier"] = "POSSIBLE_BUY"
            x["below_cut"] = cap is not None and x.get("rank", 1) > cap
        for x in lane.get("buys", []):
            x["below_cut"] = cap is not None and x.get("rank", 1) > cap
        for x in lane.get("blocked", []):
            x["tier"] = "WONT"
        for k in ("sells", "buys", "queued", "blocked"):
            for x in lane.get(k, []):
                tally[x["tier"]] += 1
    plan["tiers"] = tally
    return plan


def _ny_day(stamp: Optional[str]) -> Optional[str]:
    if not stamp:
        return None
    try:
        return datetime.fromisoformat(str(stamp)).astimezone(NY).date().isoformat()
    except ValueError:
        return None


def review(store: Any, fictional: bool, session_date: str) -> dict[str, Any]:
    """Planned versus taken for one session: did each planned line happen, and what was taken without a plan."""
    try:
        plan = json.loads(store.get_state(f"{STATE_KEY}:{session_date}", "") or "{}")
    except ValueError:
        plan = {}
    if not plan:
        return {"date": session_date, "status": "NO_PLAN"}
    lines: list[dict[str, Any]] = []
    unplanned: list[dict[str, Any]] = []
    for lane in plan.get("lanes", []):
        trades = store.lane_trades(lane["lane"], fictional, 2000)
        opened = [t for t in trades if _ny_day(t["opened_at"]) == session_date]
        closed = [t for t in trades if _ny_day(t.get("closed_at")) == session_date]
        used: set[int] = set()
        for x in lane.get("buys", []) + lane.get("queued", []):
            hit = next((t for t in opened if t["id"] not in used and t["symbol"] == x["symbol"]
                        and (x["right"] == "SHARES" or (t["open_payload"] or {}).get("right") == x["right"])), None)
            if hit:
                used.add(hit["id"])
            lines.append({"lane": lane["lane"], "label": lane.get("label"), "side": "BUY", "symbol": x["symbol"], "right": x["right"],
                          "tier": x.get("tier"), "rank": x.get("rank"), "planned_contract": x.get("contract"),
                          "taken": bool(hit), "taken_contract": (hit["open_payload"] or {}).get("contract") if hit else None,
                          "taken_at": hit["opened_at"] if hit else None})
        for x in lane.get("sells", []):
            hit = next((t for t in closed if t["symbol"] == x["symbol"] and (x.get("contract") is None
                        or (t["open_payload"] or {}).get("contract") == x.get("contract"))), None)
            lines.append({"lane": lane["lane"], "label": lane.get("label"), "side": "SELL", "symbol": x["symbol"], "right": x.get("right"),
                          "tier": x.get("tier"), "planned_reason": x.get("reason"), "taken": bool(hit),
                          "taken_reason": hit.get("close_reason") if hit else None, "taken_at": hit.get("closed_at") if hit else None})
        unplanned += [{"lane": lane["lane"], "label": lane.get("label"), "symbol": t["symbol"],
                       "contract": (t["open_payload"] or {}).get("contract"), "opened_at": t["opened_at"]}
                      for t in opened if t["id"] not in used]

    def rate(tier: str) -> dict[str, int]:
        rows = [r for r in lines if r["tier"] == tier]
        return {"planned": len(rows), "taken": sum(r["taken"] for r in rows)}
    return {"date": session_date, "status": "REVIEWED", "plan_built_at": plan.get("built_at"), "lines": lines,
            "unplanned": unplanned, "by_tier": {t: rate(t) for t in ("WILL_SELL", "LIKELY_SELL", "LIKELY_BUY", "POSSIBLE_BUY")}}


def review_history(store: Any, fictional: bool, now: datetime, limit: int = 20) -> dict[str, Any]:
    """Hit rate by tier over every session that has started and had a plan."""
    try:
        dates = json.loads(store.get_state(f"{STATE_KEY}:index", "") or "[]")
    except ValueError:
        dates = []
    today = now.astimezone(NY)
    started = [d for d in dates if d < today.date().isoformat() or (d == today.date().isoformat() and today.time() >= OPEN)]
    sessions = [review(store, fictional, d) for d in sorted(started)[-limit:]]
    sessions = [s for s in sessions if s["status"] == "REVIEWED"]
    totals = {t: {"planned": sum(s["by_tier"][t]["planned"] for s in sessions), "taken": sum(s["by_tier"][t]["taken"] for s in sessions)}
              for t in ("WILL_SELL", "LIKELY_SELL", "LIKELY_BUY", "POSSIBLE_BUY")}
    return {"sessions": len(sessions), "by_tier": totals, "unplanned": sum(len(s["unplanned"]) for s in sessions),
            "latest": sessions[-1] if sessions else None}


def due(engine: Any, now: datetime) -> bool:
    """Build once per closed period: after a close (plus a margin for the final bar) and before the next open."""
    if session_status(now)[0]:
        return False
    closed = last_close(now)
    if closed is not None and now - closed < BUILD_AFTER_CLOSE:
        return False
    session = next_session(now)
    if session is None:
        return False
    try:
        old = json.loads(engine.store.get_state(STATE_KEY, "") or "{}")
    except ValueError:
        old = {}
    built = old.get("built_at")
    if (old.get("next_session") or {}).get("date") != session["date"] or not built:
        return True
    return closed is not None and datetime.fromisoformat(built) < closed


def refresh(engine: Any, now: Optional[datetime] = None) -> dict[str, Any]:
    plan = add_tiers(build_plan(engine, now))
    raw = json.dumps(plan, default=str)
    engine.store.set_state(STATE_KEY, raw)
    day = (plan.get("next_session") or {}).get("date")
    if day:                                             # one plan per session, kept to check it against what happened
        engine.store.set_state(f"{STATE_KEY}:{day}", raw)
        try:
            index = json.loads(engine.store.get_state(f"{STATE_KEY}:index", "") or "[]")
        except ValueError:
            index = []
        engine.store.set_state(f"{STATE_KEY}:index", json.dumps(sorted(set(index) | {day})[-60:]))
    return plan


def saved(store: Any) -> Optional[dict[str, Any]]:
    try:
        raw = store.get_state(STATE_KEY, "")
        return json.loads(raw) if raw else None
    except ValueError:
        return None
