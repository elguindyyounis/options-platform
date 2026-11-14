"""The committee: combines agent verdicts, sizes the order, and learns how much to trust each agent.

Authority is bounded by construction. The committee can say no to a candidate or take LESS than the engine's size
cap. It cannot add a candidate the strategy did not propose, cannot exceed the cap, and every order it allows still
goes through the risk gate. Inside those bounds it adapts on its own: agent weights are refit from how past votes
turned out, and its own trust (which sets how much of the cap it uses) rises and falls with its hit rate.
Mistakes are expected and cheap here: this is paper trading. Nothing in this module claims an edge.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional

from .agents import ABSTAIN, ANALYST, ANALYSTS, CHECKERS, OPPOSE, SUPPORT, Context, Verdict, run_agent
from .journal import MIN_SAMPLE, OK, forward_return
from .store import Store

KIND = "COMMITTEE"
ENTER, REJECT = "WOULD_ENTER", "WOULD_REJECT"
ENTRY_THRESHOLD = 0.25
VETO_MIN_WEIGHT = 0.5      # below this a learnable veto is only a strong objection
WEIGHT_MIN, WEIGHT_MAX = 0.25, 2.0
SHRINK_K = 30              # outcomes needed before an agent's record counts for half
LEARN_WINDOW = 500         # newest decisions only: the market changes, so old lessons fade
LEARN_HORIZON_H = 4        # short enough to adapt within days
START_WEIGHT = {"sentiment": 0.25, "flow": 0.25}  # experimental signal: earns influence, does not start with it
TRUST_START, TRUST_MIN = 0.5, 0.2
COMMITTEE_AGENT = "committee"


@dataclass(frozen=True)
class CommitteeDecision:
    disposition: str
    quantity: int
    net_score: float
    scale: float
    reasons: tuple[str, ...]
    verdicts: tuple[Verdict, ...]

    def to_payload(self, weights: dict[str, float], trust: float) -> dict[str, Any]:
        return {"net_score": round(self.net_score, 3), "quantity": self.quantity, "scale": round(self.scale, 3),
                "reasons": list(self.reasons), "verdicts": [v.to_dict() for v in self.verdicts],
                "weights": {k: round(v, 3) for k, v in weights.items()}, "trust": round(trust, 3)}


def start_weight(agent: str) -> float:
    return START_WEIGHT.get(agent, 1.0)


def decide(ctx: Context, weights: dict[str, float], trust: float) -> CommitteeDecision:
    verdicts = tuple(run_agent(f, ctx) for f in ANALYSTS + CHECKERS)
    w = lambda v: weights.get(v.agent, start_weight(v.agent))  # noqa: E731
    reasons: list[str] = []
    hard = [v for v in verdicts if v.hard_veto]
    if hard:
        return CommitteeDecision(REJECT, 0, 0.0, 0.0, tuple(f"{v.agent}: {v.reasons[0]}" for v in hard), verdicts)
    vetoes = [v for v in verdicts if v.veto and w(v) >= VETO_MIN_WEIGHT]
    if vetoes:
        return CommitteeDecision(REJECT, 0, 0.0, 0.0, tuple(f"{v.agent} vetoed: {v.reasons[0]}" for v in vetoes), verdicts)
    net = 0.0
    for v in verdicts:
        if v.stance == SUPPORT:
            net += w(v) * v.confidence
        elif v.stance == OPPOSE:
            net -= w(v) * v.confidence * (1.0 if v.role == ANALYST else 0.5)
    supporters = [v for v in verdicts if v.stance == SUPPORT and w(v) * v.confidence > 0]
    if net < ENTRY_THRESHOLD or not supporters:
        reasons.append(f"net conviction {net:.2f} is below {ENTRY_THRESHOLD}")
        return CommitteeDecision(REJECT, 0, net, 0.0, tuple(reasons), verdicts)
    # Sizing: start at the committee's earned trust, adjust for conviction, then shrink for regime and crowding.
    by = {v.agent: v for v in verdicts}
    conviction = max(0.0, min(1.0, net / 1.5))
    scale = trust * (0.5 + 0.5 * conviction)
    if by["volatility"].evidence.get("regime") == "HIGH_VOL":
        scale *= 0.5
        reasons.append("high-volatility regime: size halved")
    if by["exposure"].stance == OPPOSE:
        scale *= 0.5
        reasons.append("portfolio already loaded: size halved")
    if by["skeptic"].stance == OPPOSE:
        scale *= 0.5
        reasons.append("skeptic has a major objection: size halved")
    scale = max(0.1, min(1.0, scale))
    qty = max(1, math.floor(ctx.size_cap * scale + 1e-9)) if ctx.size_cap >= 1 else 0
    qty = min(qty, ctx.size_cap)  # never above the engine's cap
    if qty == 0:
        return CommitteeDecision(REJECT, 0, net, scale, ("nothing fits within the size cap",), verdicts)
    reasons.insert(0, f"net conviction {net:.2f}, trust {trust:.2f}, using {qty} of at most {ctx.size_cap}")
    return CommitteeDecision(ENTER, qty, net, scale, tuple(reasons), verdicts)


# ------------------------------------------------------------------ learning
def _matured(store: Store, now: datetime, fictional: bool, horizon_h: float, window: int = LEARN_WINDOW) -> list[tuple[dict[str, Any], float]]:
    rows = [d for d in store.list_decisions(kind=KIND, newest_first=True, limit=window) if d["fictional"] == fictional]
    out = []
    for d in rows:
        status, ret = forward_return(store, d, horizon_h, now)
        if status == OK and ret is not None:
            out.append((d, ret))
    return out


def _correct(stance: str, ret: float) -> Optional[bool]:
    if stance == SUPPORT:
        return ret > 0
    if stance == OPPOSE:
        return ret <= 0
    return None


def fit(store: Store, now: datetime, fictional: bool) -> dict[str, dict[str, Any]]:
    """Weights and trust as a pure function of the journal, so refitting is repeatable and cannot drift."""
    hits: dict[str, list[bool]] = {}
    enter_hits: list[bool] = []
    for d, ret in _matured(store, now, fictional, LEARN_HORIZON_H):
        if d["disposition"] == ENTER:
            enter_hits.append(ret > 0)
        for v in d["payload"].get("verdicts", []):
            ok = _correct(v["stance"], ret)
            if ok is not None:
                hits.setdefault(v["agent"], []).append(ok)
    out: dict[str, dict[str, Any]] = {}
    for agent in {a.__name__ for a in ANALYSTS + CHECKERS} | set(hits):
        h = hits.get(agent, [])
        n, acc = len(h), (sum(h) / len(h) if h else None)
        start = start_weight(agent)
        target = start if acc is None else max(WEIGHT_MIN, min(WEIGHT_MAX, acc / 0.5))
        out[agent] = {"weight": round(start + (target - start) * n / (n + SHRINK_K), 3), "n": n,
                      "accuracy": None if acc is None else round(acc, 3)}
    n = len(enter_hits)
    rate = sum(enter_hits) / n if n else 0.5
    shrunk = 0.5 + (rate - 0.5) * n / (n + SHRINK_K)
    out[COMMITTEE_AGENT] = {"weight": round(max(TRUST_MIN, min(1.0, TRUST_START + 2 * (shrunk - 0.5))), 3), "n": n,
                            "accuracy": None if not n else round(rate, 3)}
    return out


def learn(store: Store, now: datetime, fictional: bool) -> dict[str, dict[str, Any]]:
    """Refit and write an audit row for every weight that moved. Returns the fitted values."""
    fitted = fit(store, now, fictional)
    latest = store.latest_agent_weights(fictional)
    for agent, f in fitted.items():
        before = latest.get(agent, {}).get("weight", start_weight(agent) if agent != COMMITTEE_AGENT else TRUST_START)
        if abs(f["weight"] - before) >= 0.02:
            acc = "no outcomes yet" if f["accuracy"] is None else f"{f['accuracy']:.0%} correct"
            store.record_agent_weight(now, agent, f["weight"], f["n"], f["accuracy"], fictional,
                                      f"{before:.2f} to {f['weight']:.2f}: {acc} over {f['n']} outcomes at {LEARN_HORIZON_H}h")
    return fitted


def current(store: Store, fictional: bool) -> tuple[dict[str, float], float]:
    stored = store.latest_agent_weights(fictional)
    weights = {a.__name__: stored.get(a.__name__, {}).get("weight", start_weight(a.__name__)) for a in ANALYSTS + CHECKERS}
    return weights, stored.get(COMMITTEE_AGENT, {}).get("weight", TRUST_START)


# ------------------------------------------------------------------ review
def scorecard(store: Store, now: datetime, fictional: bool) -> dict[str, Any]:
    """What each agent said, what happened next, and plain-language lessons from the worst calls."""
    per: dict[str, dict[str, list[float]]] = {}
    groups: dict[str, list[float]] = {ENTER: [], REJECT: []}
    mature = _matured(store, now, fictional, LEARN_HORIZON_H)
    for d, ret in mature:
        groups.setdefault(d["disposition"], []).append(ret)
        for v in d["payload"].get("verdicts", []):
            per.setdefault(v["agent"], {}).setdefault(v["stance"], []).append(ret)

    def stats(xs: list[float]) -> dict[str, Any]:
        return {"n": len(xs), "mean_return_pct": round(sum(xs) / len(xs), 2) if xs else None,
                "hit_rate": round(sum(x > 0 for x in xs) / len(xs), 3) if xs else None}

    weights, trust = current(store, fictional)
    agents = {}
    for name, by_stance in sorted(per.items()):
        agents[name] = {"weight": weights.get(name), "votes": {s: stats(r) for s, r in by_stance.items()},
                        "descriptive_only": min(len(by_stance.get(SUPPORT, [])), len(by_stance.get(OPPOSE, []))) < MIN_SAMPLE}
    return {"horizon_hours": LEARN_HORIZON_H, "trust": trust, "weights": weights,
            "committee": {k: stats(v) for k, v in groups.items()}, "agents": agents,
            "history": store.list_agent_weights(fictional, limit=20), "lessons": lessons(mature),
            "caveat": "Outcomes are the contract's bid versus the candidate's limit price a few hours later, from recorded "
                      "delayed data. Overlapping candidates are not independent. This measures learning, not an edge."}


def lessons(mature: list[tuple[dict[str, Any], float]], top: int = 3) -> list[str]:
    out: list[str] = []
    entered = sorted((m for m in mature if m[0]["disposition"] == ENTER and m[1] < 0), key=lambda m: m[1])[:top]
    missed = sorted((m for m in mature if m[0]["disposition"] == REJECT and m[1] > 0), key=lambda m: -m[1])[:top]
    for kind, items in (("Entered and lost", entered), ("Rejected but would have gained", missed)):
        for d, ret in items:
            vs = d["payload"].get("verdicts", [])
            wrong = [v["agent"] for v in vs if (_correct(v["stance"], ret) is False)]
            right = [v["agent"] for v in vs if (_correct(v["stance"], ret) is True)]
            out.append(f"{kind}: {d['contract']} {ret:+.1f}% after {LEARN_HORIZON_H}h ({d['ts'][:16]}). "
                       f"Wrong: {', '.join(wrong) or 'none'}. Right: {', '.join(right) or 'none'}.")
    return out
