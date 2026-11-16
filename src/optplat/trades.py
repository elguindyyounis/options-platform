"""Turn the order ledger into trades a person can read: entry, exit, result, and the reasoning behind each.

A trade is one filled BUY_TO_OPEN. Filled SELL_TO_CLOSE orders on the same contract are matched to entries oldest
first. Open quantity is marked at the bid; if no valid bid exists the mark is None and the result is "unobservable",
never a guess. Everything is derived from stored orders and the decision journal, so it cannot drift from them.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Any, Optional

from .models import Order, OrderState, Side
from .orders import OrderManager

FILLED_STATES = (OrderState.FILLED, OrderState.PARTIALLY_FILLED)


def _decision_by_order(store: Any, kind: str) -> dict[str, dict[str, Any]]:
    return {d["order_id"]: d for d in store.list_decisions(kind=kind, limit=2000) if d.get("order_id")}


def _committee_index(store: Any) -> dict[str, list[dict[str, Any]]]:
    """Committee votes grouped by contract, oldest first: read once, not once per trade."""
    index: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for d in store.list_decisions(kind="COMMITTEE", newest_first=False, limit=5000):
        index[d["contract"]].append(d)
    return index


def _committee_for(index: dict[str, list[dict[str, Any]]], contract: str, before: datetime) -> Optional[dict[str, Any]]:
    best = None
    for d in index.get(contract, ()):
        if datetime.fromisoformat(d["ts"]) <= before:
            best = d  # the list is oldest first, so the last match is the latest vote at or before the entry
    return best


def build_trades(manager: OrderManager, limit: int = 300) -> dict[str, Any]:
    store = manager.store
    # list_orders is newest first by (created_at, insertion order). Reversing it gives oldest first and keeps the
    # recorded sequence for orders with the same timestamp, so an exit is never processed before its own entry.
    orders = [o for o in reversed(store.list_orders(limit=2000)) if o.state in FILLED_STATES and o.filled_qty > 0 and o.avg_fill_price]
    entry_decisions, exit_decisions = _decision_by_order(store, "ENTRY"), _decision_by_order(store, "EXIT")
    committee_index = _committee_index(store)
    lots: dict[str, list[dict[str, Any]]] = defaultdict(list)
    trades: list[dict[str, Any]] = []
    for o in orders:
        contract = o.intent.contract
        key = contract.occ_symbol.strip()
        if o.intent.side is Side.BUY_TO_OPEN:
            t = {"id": o.id, "contract": key, "symbol": contract.underlying, "right": contract.right.value,
                 "strike": contract.strike, "expiry": contract.expiry.isoformat(), "quantity": o.filled_qty,
                 "entry_time": o.updated_at.isoformat(), "entry_price": o.avg_fill_price, "exit_orders": [],
                 "exited_qty": 0, "exit_value": 0.0, "multiplier": contract.multiplier, "_contract": contract,
                 "_entry_order": o}
            lots[key].append(t)
            trades.append(t)
        elif o.intent.side is Side.SELL_TO_CLOSE:
            remaining = o.filled_qty
            for lot in lots[key]:
                room = lot["quantity"] - lot["exited_qty"]
                if room <= 0 or remaining <= 0:
                    continue
                take = min(room, remaining)
                lot["exited_qty"] += take
                lot["exit_value"] += take * o.avg_fill_price
                lot["exit_orders"].append({"order_id": o.id, "quantity": take, "price": o.avg_fill_price, "time": o.updated_at.isoformat()})
                remaining -= take
    out: list[dict[str, Any]] = []
    for t in trades:
        contract, entry_order = t.pop("_contract"), t.pop("_entry_order")
        qty, done, mult, entry = t["quantity"], t["exited_qty"], t["multiplier"], t["entry_price"]
        rem = qty - done
        realized = round(t["exit_value"] * mult - entry * done * mult, 2)
        mark = None
        if rem > 0:
            try:
                q = manager.broker.get_quote(contract)
                if q.is_valid() and q.bid > 0:
                    mark = q.bid
            except Exception:  # noqa: BLE001 - unobservable is reported, not guessed
                mark = None
        unrealized = round((mark - entry) * rem * mult, 2) if mark is not None else None
        cost = entry * qty * mult
        total = None if (rem > 0 and unrealized is None) else round(realized + (unrealized or 0.0), 2)
        status = "CLOSED" if rem == 0 else ("PARTIAL" if done > 0 else "OPEN")
        last_exit = t["exit_orders"][-1] if t["exit_orders"] else None
        ed = exit_decisions.get(last_exit["order_id"]) if last_exit else None
        en = entry_decisions.get(t["id"])
        committee = _committee_for(committee_index, t["contract"], entry_order.updated_at)
        held_to = datetime.fromisoformat(last_exit["time"]) if (last_exit and rem == 0) else None
        t.update({
            "status": status, "remaining": rem, "mark": mark, "realized_pnl": realized, "unrealized_pnl": unrealized,
            "pnl": total, "pnl_pct": None if total is None or cost <= 0 else round(total / cost * 100, 2),
            "exit_price": round(t["exit_value"] / done, 4) if done else None,
            "exit_time": last_exit["time"] if last_exit else None,
            "held_seconds": int(((held_to or None) - datetime.fromisoformat(t["entry_time"])).total_seconds()) if held_to else None,
            "exit_reason": (ed["payload"].get("trigger") or ed["payload"].get("reason") or ed["disposition"]) if ed else None,
            "entry_reason": en["payload"].get("rationale") if en else None,
            "committee": None if committee is None else {k: committee["payload"].get(k) for k in
                                                          ("net_score", "quantity", "scale", "reasons", "verdicts", "trust")},
        })
        t.pop("exit_value", None)
        out.append(t)
    out.sort(key=lambda x: x["entry_time"], reverse=True)
    closed = [t for t in out if t["status"] == "CLOSED"]
    wins = [t for t in closed if (t["pnl"] or 0) > 0]
    summary = {
        "total": len(out), "open": sum(t["status"] != "CLOSED" for t in out), "closed": len(closed),
        "wins": len(wins), "win_rate_pct": round(len(wins) / len(closed) * 100, 1) if closed else None,
        "realized_pnl": round(sum(t["realized_pnl"] for t in out), 2),
        "unrealized_pnl": round(sum(t["unrealized_pnl"] or 0.0 for t in out), 2),
        "unobservable_open": sum(1 for t in out if t["remaining"] > 0 and t["mark"] is None),
        "best": max((t["pnl"] for t in closed if t["pnl"] is not None), default=None),
        "worst": min((t["pnl"] for t in closed if t["pnl"] is not None), default=None),
        "caveat": "Paper trades with simulated fills. A small number of trades says nothing about a real edge.",
    }
    return {"summary": summary, "trades": out[: max(1, min(limit, 1000))]}


def trade_detail(manager: OrderManager, trade_id: str) -> Optional[dict[str, Any]]:
    found = next((t for t in build_trades(manager, 1000)["trades"] if t["id"] == trade_id), None)
    if found is None:
        return None
    store = manager.store
    events = list(store.audit_events(trade_id))
    for x in found["exit_orders"]:
        events += store.audit_events(x["order_id"])
    events.sort(key=lambda e: e["ts"])
    return {**found, "audit": events}
