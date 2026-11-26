"""Compare the simulated main account with its IBKR paper mirror, order by order (read-only).

The simulator is the account of record; IBKR paper is a second, independent fill model. For each order the simulator
accepted, this pairs its simulated fill with the last IBKR outcome in the audit log (``ibkr_mirror_*``) and reports how
often IBKR filled and at what price. A price gap is shown from the trader's side: positive means IBKR's fill was
better (paid less on a buy, got more on a sell). IBKR paper fills come from IBKR's own simulator, not a real market,
so a gap here measures two models against each other and proves nothing about live execution.

Run: ``python -m optplat.mirror_report --db <path>`` (opens the database read-only).
"""
from __future__ import annotations

import argparse
import json
import statistics
from collections import Counter
from typing import Any, Optional, Sequence

from .models import STATUS_FILLED, STATUS_PARTIALLY_FILLED, Order
from .store import Store

OUTCOME_KINDS = ("ibkr_mirror_submitted", "ibkr_mirror_status", "ibkr_mirror_cancelled")
BUY_SIDES = ("BUY_TO_OPEN", "BUY_TO_CLOSE")
ORDER_SCAN_LIMIT = 100_000


def _pair_rows(orders: Sequence[Order], events: Sequence[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    last: dict[str, dict[str, Any]] = {}
    rejected: Counter[str] = Counter()
    errors: Counter[str] = Counter()
    dropped = 0
    for e in events:  # oldest first, so the last outcome per key wins
        kind, p = e["kind"], e["payload"]
        key = p.get("idempotency_key")
        if kind in OUTCOME_KINDS and key:
            last[key] = {**last.get(key, {}), **p, "kind": kind, "ts": e["ts"]}
        elif kind == "ibkr_mirror_rejected":
            rejected[str(p.get("reason", "?"))[:80]] += 1
            if key:
                last[key] = {**p, "status": "REJECTED", "filled_qty": 0, "avg_fill_price": None, "kind": kind,
                             "ts": e["ts"]}
        elif kind in ("ibkr_mirror_error", "ibkr_mirror_cancel_error"):
            errors[str(p.get("error", "?"))] += 1
        elif kind == "ibkr_mirror_dropped":
            dropped += 1
    by_key = {o.intent.idempotency_key: o for o in orders}
    rows = []
    for key, ib in last.items():
        o = by_key.get(key)
        if o is None:
            continue
        side = o.intent.side.value
        sim_px, ib_px = o.avg_fill_price, ib.get("avg_fill_price")
        both = min(o.filled_qty, int(ib.get("filled_qty") or 0))
        gap: Optional[float] = None
        if both > 0 and sim_px is not None and ib_px is not None:
            gap = (sim_px - ib_px) if side in BUY_SIDES else (ib_px - sim_px)
        rows.append({
            "idempotency_key": key, "contract": o.intent.contract.occ_symbol, "side": side,
            "quantity": o.intent.quantity, "limit_price": o.intent.limit_price,
            "sim_state": o.state.value, "sim_filled_qty": o.filled_qty, "sim_avg_fill_price": sim_px,
            "ibkr_status": ib.get("status"), "ibkr_filled_qty": int(ib.get("filled_qty") or 0),
            "ibkr_avg_fill_price": ib_px, "ibkr_last_seen": ib["ts"],
            "ibkr_better_by_per_share": None if gap is None else round(gap, 4),
            "ibkr_better_by_usd": None if gap is None else round(gap * both * o.intent.contract.multiplier, 2),
        })
    extra = {"rejected_reasons": dict(rejected), "error_types": dict(errors), "dropped": dropped,
             "outcomes_without_a_local_order": len([k for k in last if k not in by_key])}
    return rows, extra


def report(store: Store) -> dict[str, Any]:
    orders = store.list_orders(limit=ORDER_SCAN_LIMIT)
    events = [e for e in store.audit_events() if e["kind"].startswith("ibkr_mirror_")]
    rows, extra = _pair_rows(orders, events)
    sim_filled = [r for r in rows if r["sim_filled_qty"] > 0]
    ib_filled = [r for r in rows if r["ibkr_filled_qty"] > 0]
    gaps = [r["ibkr_better_by_per_share"] for r in rows if r["ibkr_better_by_per_share"] is not None]
    working = [r for r in rows if r["ibkr_status"] in ("SUBMITTED", STATUS_PARTIALLY_FILLED)]
    summary = {
        "mirrored_orders": len(rows),
        "sim_filled": len(sim_filled),
        "ibkr_filled": len(ib_filled),
        "ibkr_fully_filled": len([r for r in rows if r["ibkr_status"] == STATUS_FILLED]),
        "both_filled": len(gaps),
        "sim_filled_ibkr_not": len([r for r in sim_filled if r["ibkr_filled_qty"] == 0]),
        "ibkr_filled_sim_not": len([r for r in ib_filled if r["sim_filled_qty"] == 0]),
        "ibkr_last_known_working": len(working),
        "ibkr_better_by_per_share_mean": round(statistics.fmean(gaps), 4) if gaps else None,
        "ibkr_better_by_per_share_median": round(statistics.median(gaps), 4) if gaps else None,
        "ibkr_better_by_usd_total": round(sum(r["ibkr_better_by_usd"] for r in rows
                                              if r["ibkr_better_by_usd"] is not None), 2),
        **extra,
    }
    notes = ["IBKR paper fills come from IBKR's simulator, not a real market: this compares two models and proves "
             "nothing about live execution."]
    if len(gaps) < 30:
        notes.append(f"Only {len(gaps)} orders filled in both books; too few to say which fill model is kinder.")
    if working:
        notes.append(f"{len(working)} orders were last seen still working at IBKR; their final outcome is not recorded "
                     "(audited read-back started 2026-11-27, and it is not kept across restarts).")
    return {"summary": summary, "notes": notes, "orders": sorted(rows, key=lambda r: r["ibkr_last_seen"])}


def main(argv: Optional[Sequence[str]] = None) -> None:
    ap = argparse.ArgumentParser(description="Compare simulated fills with IBKR paper mirror fills (read-only).")
    ap.add_argument("--db", default="optplat.db")
    ap.add_argument("--summary", action="store_true", help="print the summary and notes only")
    args = ap.parse_args(argv)
    out = report(Store(args.db, read_only=True))
    if args.summary:
        out.pop("orders")
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
