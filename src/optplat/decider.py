"""D1: one decider that reads every analyst's note together, instead of a weighted vote (owner idea, 2026-11-25; go-ahead 2026-11-27).

It runs in SHADOW beside the committee: each candidate the committee judges also gets a decider call, journalled as kind
DECIDER with both answers side by side. It places no order and changes no size. `compare` scores the two on the same
candidates afterwards. Pass criteria for the comparison are written in docs/EVOLUTION_PLAN.md (row D1) and are fixed.

The decider keeps every safety gate: if the committee rejected on a hard veto or a gate's veto, so does it. What differs is
the combining step. Instead of summing weighted confidences it reads the analysts as a panel:
conviction = (confidence of the analysts that support) minus (confidence of those that oppose), over the analysts that
spoke, so opposition counts as much as support. It enters only above the conviction gate (0.45, the owner's swing gate) and
sizes by conviction across the WHOLE allowed range: 25% of the engine's cap at the gate up to 100% at the top. The cap itself
is the risk policy's, untouched. It also writes down WHY it entered (the two strongest supporting reasons) and what would
make the trade wrong (the 20-day average, when the technical analyst measured it), so the exit side can hold or leave against
that thesis instead of a fixed percentage. Nothing here is validated.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional

from . import committee as cmt
from .agents import ABSTAIN, ANALYST, OPPOSE, SUPPORT, Context
from .journal import OK, forward_return
from .store import Store

KIND = "DECIDER"
GATE = 0.45
MIN_FRACTION = 0.25
MIN_COMPARED = 60


@dataclass(frozen=True)
class DeciderDecision:
    disposition: str          # ENTER or REJECT (the committee's own vocabulary)
    quantity: int
    conviction: float
    fraction: float
    thesis: tuple[str, ...]
    invalidation: Optional[dict[str, Any]]
    reasons: tuple[str, ...]

    def to_payload(self, committee: "cmt.CommitteeDecision") -> dict[str, Any]:
        return {"conviction": round(self.conviction, 3), "fraction": round(self.fraction, 3), "quantity": self.quantity,
                "thesis": list(self.thesis), "invalidation": self.invalidation, "reasons": list(self.reasons),
                "committee_disposition": committee.disposition, "committee_quantity": committee.quantity,
                "committee_net_score": round(committee.net_score, 3)}


def decide(ctx: Context, committee: "cmt.CommitteeDecision") -> DeciderDecision:
    verdicts = committee.verdicts
    if any(v.hard_veto for v in verdicts) or (committee.disposition == cmt.REJECT and any("vetoed" in r for r in committee.reasons)):
        return DeciderDecision(cmt.REJECT, 0, 0.0, 0.0, (), None, ("a safety gate or an honoured veto stands: " + "; ".join(committee.reasons[:2]),))
    panel = [v for v in verdicts if v.role == ANALYST and v.stance != ABSTAIN]
    if not panel:
        return DeciderDecision(cmt.REJECT, 0, 0.0, 0.0, (), None, ("no analyst had evidence: unknown means no trade",))
    support = [v for v in panel if v.stance == SUPPORT]
    oppose = [v for v in panel if v.stance == OPPOSE]
    conviction = (sum(v.confidence for v in support) - sum(v.confidence for v in oppose)) / len(panel)
    if conviction < GATE or not support:
        return DeciderDecision(cmt.REJECT, 0, conviction, 0.0, (), None, (f"conviction {conviction:.2f} is below the {GATE} gate",))
    fraction = MIN_FRACTION + (1 - MIN_FRACTION) * min(1.0, (conviction - GATE) / (1.0 - GATE))
    qty = min(ctx.size_cap, max(1, math.floor(ctx.size_cap * fraction + 1e-9))) if ctx.size_cap >= 1 else 0
    if qty == 0:
        return DeciderDecision(cmt.REJECT, 0, conviction, fraction, (), None, ("nothing fits within the size cap",))
    best = sorted(support, key=lambda v: -v.confidence)[:2]
    thesis = tuple(f"{v.agent}: {v.reasons[0]}" for v in best if v.reasons)
    tech = next((v for v in verdicts if v.agent == "technical" and v.stance == SUPPORT), None)
    sma20 = tech.evidence.get("sma20") if tech else None
    invalid = {"underlying_closes_through": sma20, "direction": "below" if ctx.direction > 0 else "above"} if sma20 else None
    return DeciderDecision(cmt.ENTER, qty, conviction, fraction, thesis, invalid,
                           (f"conviction {conviction:.2f} over {len(panel)} analysts: {len(support)} for, {len(oppose)} against; using {qty} of at most {ctx.size_cap}",))


def compare(store: Store, now: datetime, fictional: bool, horizon_h: float = 24.0) -> dict[str, Any]:
    """Score the decider against the committee on the same candidates: contract-weighted dollar change per candidate, with each
    side's own quantity (a REJECT counts as zero contracts). Descriptive until MIN_COMPARED candidates have matured."""
    rows = [d for d in store.list_decisions(kind=KIND, newest_first=False, limit=100_000) if d["fictional"] == fictional]
    cand = 0
    c_total = d_total = 0.0
    n = 0
    for d in rows:
        cand += 1
        status, ret = forward_return(store, d, horizon_h, now)
        if status != OK or ret is None or not d.get("ref_price"):
            continue
        p = d["payload"]
        per_contract = ret / 100 * d["ref_price"] * 100
        d_total += per_contract * (p.get("quantity") or 0)
        c_total += per_contract * (p.get("committee_quantity") or 0)
        n += 1
    return {"fictional": fictional, "horizon_hours": horizon_h, "candidates": cand, "matured": n,
            "committee_dollar_change": round(c_total, 2), "decider_dollar_change": round(d_total, 2),
            "descriptive_only": n < MIN_COMPARED,
            "caveat": "Candidates overlap in time and are not independent; this is the descriptive comparison, not the pass test "
                      "(D1 in docs/EVOLUTION_PLAN.md needs the later-30%-of-dates bootstrap on independent observations). No edge is claimed."}
