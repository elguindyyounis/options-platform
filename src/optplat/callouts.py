"""External callouts: trades another person posted (for example a Discord alert), kept as paper follows.

Research only. A callout is stored as a row in the shadow book (``shadow_follows``) so the existing machinery re-quotes it on
every scan and keeps its bid path, which any exit rule can then be replayed over. Nothing here places an order, changes a
size or feeds a strategy.

Honesty rules, fixed before any result exists:

* The posted price is taken as the entry ask. A poster's price is not a verified fill and may differ from the market at
  the time; each row says so (``entry_price_is_posted``).
* The size label (Small, Medium, Large) is kept as an ordinal 1 to 3. It is a hypothesis (C1 in docs/EVOLUTION_PLAN.md),
  not a sizing input, and nothing is said about it before at least ``MIN_FOR_INFERENCE`` resolved callouts exist.
* Callouts are kept out of the generic shadow-book gate counts and out of the independent sample used by the generic
  tests (see ``shadow.is_callout``); they are reported separately.
* Features the poster did not give (bid, spread, IV, days to earnings) are listed in ``missing_features``, never guessed.
"""
from __future__ import annotations

import argparse
import re
import sys
from datetime import date, datetime
from typing import Any, Optional

from .models import OptionContract, Right
from .shadow import MAX_AGE, is_callout

SIZE_ORDINAL = {"small": 1, "medium": 2, "large": 3}
MIN_FOR_INFERENCE = 30
_NAME = re.compile(r"^[a-z0-9_-]{1,32}$")
_SYMBOL = re.compile(r"^[A-Z]{1,6}$")


def record(store: Any, *, symbol: str, expiry: date, right: str, strike: float, price: float, size: str, source: str,
           day: date, posted_at: Optional[datetime] = None, fictional: bool = False, note: str = "") -> bool:
    """Store one callout. Returns False when the same contract was already logged that day. Raises ValueError on bad input."""
    symbol = symbol.strip().upper()
    source = source.strip().lower()
    right = right.strip().upper()
    ordinal = SIZE_ORDINAL.get(size.strip().lower())
    if not _SYMBOL.match(symbol) or not _NAME.match(source):
        raise ValueError("symbol must be 1 to 6 letters and source 1 to 32 characters of a-z, 0-9, _ or -")
    if right not in ("C", "P") or ordinal is None:
        raise ValueError("right must be C or P and size must be Small, Medium or Large")
    if not (strike > 0 and price > 0) or expiry <= day:
        raise ValueError("strike and price must be positive and the expiry must be after the day of the callout")
    contract = OptionContract(symbol, expiry, Right(right), float(strike))
    when = (posted_at or datetime(day.year, day.month, day.day)).isoformat()
    payload = {"symbol": symbol, "contract": contract.occ_symbol.strip(), "right": right, "strike": float(strike), "expiry": expiry.isoformat(),
               "dte": (expiry - day).days, "entry_ask": float(price), "entry_bid": None, "spread_pct": None, "iv": None,
               "followed_at": when, "followed_day": day.isoformat(), "source": f"callout:{source}", "size_label": size.strip().title(),
               "size_ordinal": ordinal, "entry_price_is_posted": True, "note": note[:200],
               "missing_features": ["entry_bid", "spread_pct", "iv", "iv_percentile", "days_to_earnings", "posting_time_zone"]}
    return store.record_shadow_follow(contract.occ_symbol.strip(), day.isoformat(), fictional, payload)


def open_symbols(store: Any, today: date, fictional: bool = False) -> list[str]:
    """Underlyings with a callout still inside the followed window, so the scanner reads their chains even outside the universe."""
    out = set()
    for f in store.shadow_all_follows(fictional):
        if is_callout(f) and date.fromisoformat(f["expiry"]) >= today and (today - date.fromisoformat(f["followed_day"])).days <= MAX_AGE * 2:
            out.add(f["symbol"])
    return sorted(out)


def summary(store: Any, fictional: bool, today: date) -> dict[str, Any]:
    """Each callout with its latest recorded bid against the posted entry, and a count by size label. No verdict below the minimum."""
    follows = [f for f in store.shadow_all_follows(fictional) if is_callout(f)]
    last: dict[tuple[str, str], dict[str, Any]] = {}
    for p in store.shadow_all_points(fictional):
        last[(p["contract"], p["followed_day"])] = p  # points arrive ordered by followed_day then time
    rows, by_size = [], {}
    for f in follows:
        p = last.get((f["contract"], f["followed_day"]))
        ret = round(p["bid"] / f["entry_ask"] - 1, 4) if p and p.get("bid") is not None and f.get("entry_ask") else None
        rows.append({"symbol": f["symbol"], "contract": f["contract"], "source": f["source"], "followed_day": f["followed_day"], "size": f.get("size_label"),
                     "entry_price_posted": f.get("entry_ask"), "latest_bid": p.get("bid") if p else None, "latest_observed_day": p.get("observed_day") if p else None,
                     "return_to_latest_bid": ret, "expired": date.fromisoformat(f["expiry"]) < today})
        by_size[f.get("size_label")] = by_size.get(f.get("size_label"), 0) + 1
    resolved = sum(1 for r in rows if r["return_to_latest_bid"] is not None)
    return {"fictional": fictional, "count": len(rows), "with_a_recorded_bid": resolved, "by_size": by_size, "callouts": rows,
            "minimum_for_inference": MIN_FOR_INFERENCE, "inference_allowed": resolved >= MIN_FOR_INFERENCE,
            "note": "Posted prices are not verified fills. Returns are the latest recorded bid against the posted price, before any stressed exit. "
                    "Nothing is concluded about size labels or callers below the minimum; this is a log, not evidence of an edge."}


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(description="Log a callout (paper research only) into the platform database")
    p.add_argument("--db", required=True)
    p.add_argument("--symbol", required=True)
    p.add_argument("--expiry", required=True, help="YYYY-MM-DD")
    p.add_argument("--right", default="C")
    p.add_argument("--strike", type=float, required=True)
    p.add_argument("--price", type=float, required=True, help="posted entry price")
    p.add_argument("--size", required=True, help="Small, Medium or Large")
    p.add_argument("--source", required=True, help="who posted it, e.g. buddybear")
    p.add_argument("--day", required=True, help="day posted, YYYY-MM-DD (US market date)")
    p.add_argument("--note", default="")
    a = p.parse_args(argv)
    from .store import Store
    try:
        ok = record(Store(a.db), symbol=a.symbol, expiry=date.fromisoformat(a.expiry), right=a.right, strike=a.strike, price=a.price,
                    size=a.size, source=a.source, day=date.fromisoformat(a.day), note=a.note)
    except ValueError as exc:
        print(f"not logged: {exc}", file=sys.stderr)
        return 2
    print("logged" if ok else "already logged for that day")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
