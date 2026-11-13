"""Research-only counterfactual journal: what would a setup have done had we taken it?

Records setups the platform rejected or did not select (and ones it took), then re-marks them at
fixed horizons from later quotes. Display/analysis only: it never creates orders, never touches
risk, and is not wired into the engine.

Honesty rules, borrowed from the owner's options-alerter ``feedback.py`` and made stricter:

* Returns are ask-plus-slippage in, later-bid-minus-slippage out. They are INDICATIVE, never fills.
* A later quote only counts if it is clearly after the decision (``MIN_GAP``), so a same-session
  re-quote cannot masquerade as a 1-day outcome.
* Cases with no usable later quote become NO_DATA and are counted in every summary. Dropping them
  silently would flatter the result (survivorship), so the summary reports the unresolved share.
* No summary is called a result below ``MIN_RESOLVED`` resolved cases per decision and horizon.
"""
from __future__ import annotations

import json
import math
import statistics
from datetime import datetime, timedelta
from typing import Any, Iterable, Mapping, Optional

from .models import Quote, utcnow

HORIZONS = (1, 7, 30)
MIN_GAP = timedelta(hours=12)
MIN_RESOLVED = 30
DECISIONS = ("REJECTED", "NOT_SELECTED", "TAKEN")
NOTE = "Hypothetical ask-to-bid marks from recorded quotes. Not fills, not a result, not evidence of an edge."

SCHEMA = """
CREATE TABLE IF NOT EXISTS counterfactuals (
    id TEXT PRIMARY KEY,
    setup_id TEXT NOT NULL,
    contract_key TEXT NOT NULL,
    decision TEXT NOT NULL,
    reason TEXT NOT NULL,
    captured_at TEXT NOT NULL,
    due_at TEXT NOT NULL,
    horizon_days INTEGER NOT NULL,
    entry_ask REAL NOT NULL,
    status TEXT NOT NULL DEFAULT 'PENDING',
    return_pct REAL,
    evaluated_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_cf_status_due ON counterfactuals(status, due_at);
"""


def _ok(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def hypothetical_return_pct(entry_ask: float, later_bid: float, slippage_pct: float = 0.5) -> Optional[float]:
    """Premium return buying at ask+slippage and selling at bid-slippage. None if inputs unusable."""
    if not (_ok(entry_ask) and _ok(later_bid) and _ok(slippage_pct)):
        return None
    if entry_ask <= 0 or later_bid < 0 or not (0 <= slippage_pct <= 3):
        return None
    cost = entry_ask * (1 + slippage_pct / 100)
    proceeds = later_bid * (1 - slippage_pct / 100)
    return round((proceeds / cost - 1) * 100, 2)


class CounterfactualJournal:
    def __init__(self, store: Any) -> None:
        self._store = store
        with store._lock:
            store._db.executescript(SCHEMA)
            store._db.commit()

    def record(
        self,
        *,
        setup_id: str,
        contract_key: str,
        decision: str,
        reason: str,
        quote: Quote,
        now: Optional[datetime] = None,
    ) -> int:
        """Store one pending case per horizon. Unknown decisions or unusable quotes are refused."""
        if decision not in DECISIONS or not quote.is_valid():
            return 0
        now = now or utcnow()
        created = 0
        with self._store._lock:
            for days in HORIZONS:
                cur = self._store._db.execute(
                    "INSERT OR IGNORE INTO counterfactuals (id, setup_id, contract_key, decision, reason,"
                    " captured_at, due_at, horizon_days, entry_ask) VALUES (?,?,?,?,?,?,?,?,?)",
                    (f"{setup_id}:{days}", setup_id, contract_key, decision, reason[:240], now.isoformat(),
                     (now + timedelta(days=days)).isoformat(), days, quote.ask),
                )
                created += cur.rowcount
            self._store._db.commit()
        return created

    def mark(
        self, quotes: Mapping[str, Quote], *, now: Optional[datetime] = None, slippage_pct: float = 0.5
    ) -> dict[str, int]:
        """Resolve due cases from ``quotes`` (contract_key -> latest quote)."""
        now = now or utcnow()
        evaluated = no_data = 0
        with self._store._lock:
            rows = self._store._db.execute(
                "SELECT * FROM counterfactuals WHERE status='PENDING' AND due_at<=? ORDER BY due_at LIMIT 500",
                (now.isoformat(),),
            ).fetchall()
            for r in rows:
                q = quotes.get(r["contract_key"])
                captured = datetime.fromisoformat(r["captured_at"])
                pct = None
                if q is not None and q.is_valid() and q.as_of >= captured + MIN_GAP:
                    pct = hypothetical_return_pct(r["entry_ask"], q.bid, slippage_pct)
                if pct is not None:
                    self._store._db.execute(
                        "UPDATE counterfactuals SET status='EVALUATED', return_pct=?, evaluated_at=? WHERE id=?",
                        (pct, now.isoformat(), r["id"]),
                    )
                    evaluated += 1
                else:
                    grace = timedelta(days=max(4, min(10, r["horizon_days"] // 3)))
                    if now >= datetime.fromisoformat(r["due_at"]) + grace:
                        self._store._db.execute(
                            "UPDATE counterfactuals SET status='NO_DATA', evaluated_at=? WHERE id=?",
                            (now.isoformat(), r["id"]),
                        )
                        no_data += 1
            self._store._db.commit()
        return {"evaluated": evaluated, "no_data": no_data}

    def summary(self) -> dict[str, Any]:
        """Per decision and horizon: resolved, unresolved, pending, mean/median, and a sample gate."""
        with self._store._lock:
            rows = self._store._db.execute(
                "SELECT decision, horizon_days, status, return_pct FROM counterfactuals"
            ).fetchall()
        groups: dict[tuple[str, int], dict[str, Any]] = {}
        for r in rows:
            g = groups.setdefault((r["decision"], r["horizon_days"]), {"vals": [], "no_data": 0, "pending": 0})
            if r["status"] == "EVALUATED" and r["return_pct"] is not None:
                g["vals"].append(r["return_pct"])
            elif r["status"] == "NO_DATA":
                g["no_data"] += 1
            else:
                g["pending"] += 1
        out = []
        for (decision, days), g in sorted(groups.items()):
            vals = g["vals"]
            n, closed = len(vals), len(vals) + g["no_data"]
            enough = n >= MIN_RESOLVED
            out.append(
                {
                    "decision": decision,
                    "horizon_days": days,
                    "resolved": n,
                    "no_data": g["no_data"],
                    "pending": g["pending"],
                    "unresolved_share_pct": round(100 * g["no_data"] / closed, 1) if closed else None,
                    "sample_sufficient": enough,
                    # Numbers are withheld below the gate so a thin sample cannot read as a finding.
                    "mean_return_pct": round(statistics.fmean(vals), 2) if enough else None,
                    "median_return_pct": round(statistics.median(vals), 2) if enough else None,
                    "min_resolved_required": MIN_RESOLVED,
                }
            )
        return {"rows": out, "note": NOTE}


__all__ = ["CounterfactualJournal", "hypothetical_return_pct", "HORIZONS", "MIN_RESOLVED"]
