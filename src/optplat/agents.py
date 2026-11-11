"""Analyst agents. Each reads one candidate and returns a structured, explainable Verdict.

Everything here is deterministic and rule-based: no language model is in the order path. An agent never places
an order. Missing or unknown data means ABSTAIN (an analyst) or a veto (a gate), never "assume fine".
Every threshold below is an experiment parameter, not a validated fact. The committee learns how much to trust
each agent from outcomes (see committee.py).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional, Sequence

from .events import EventView
from .marketdata import ChainRow, MarketSnapshot
from .models import Account, Position, Right
from .risk import RiskPolicy
from .signals import compute_signals
from .strategy import Proposal

SUPPORT, OPPOSE, ABSTAIN = "SUPPORT", "OPPOSE", "ABSTAIN"
ANALYST, SKEPTIC, GATE = "analyst", "skeptic", "gate"


@dataclass(frozen=True)
class Context:
    snapshot: MarketSnapshot
    proposal: Proposal
    now: datetime
    account: Account
    policy: RiskPolicy
    positions: tuple[Position, ...]
    size_cap: int  # the engine's own ceiling for this order: agents can only use less than this, never more
    min_dte_to_hold: int = 5
    stop_loss_pct: float = 30.0
    events: Optional[EventView] = None  # None: no calendar was consulted at all

    @property
    def row(self) -> Optional[ChainRow]:
        for r in self.snapshot.rows:
            if r.contract == self.proposal.contract:
                return r
        return None

    @property
    def direction(self) -> int:
        return 1 if self.proposal.contract.right is Right.CALL else -1

    @property
    def dte(self) -> int:
        return (self.proposal.contract.expiry - self.now.date()).days


@dataclass(frozen=True)
class Verdict:
    agent: str
    role: str
    stance: str
    confidence: float = 0.0
    reasons: tuple[str, ...] = ()
    evidence: dict[str, Any] = field(default_factory=dict)
    veto: bool = False        # learnable: honoured only while the agent's learned weight stays high enough
    hard_veto: bool = False   # data-integrity or safety: never softened by learning
    experimental: bool = False  # uses an unvalidated signal; its learned weight starts low

    def to_dict(self) -> dict[str, Any]:
        return {"agent": self.agent, "role": self.role, "stance": self.stance, "confidence": round(self.confidence, 3),
                "reasons": list(self.reasons), "evidence": self.evidence, "veto": self.veto,
                "hard_veto": self.hard_veto, "experimental": self.experimental}


def _clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def sma(xs: Sequence[float], n: int) -> float:
    return sum(xs[-n:]) / n


def rsi(closes: Sequence[float], n: int = 14) -> Optional[float]:
    if len(closes) < n + 1:
        return None
    gains = losses = 0.0
    for a, b in zip(closes[-n - 1:-1], closes[-n:]):
        gains += max(0.0, b - a)
        losses += max(0.0, a - b)
    if gains + losses == 0:
        return 50.0
    return 100.0 if losses == 0 else round(100 - 100 / (1 + gains / losses), 1)


def realized_vol(closes: Sequence[float], n: int = 20) -> Optional[float]:
    """Annualised standard deviation of daily log returns over the last n returns."""
    if len(closes) < n + 1 or any(c <= 0 for c in closes[-n - 1:]):
        return None
    rets = [math.log(b / a) for a, b in zip(closes[-n - 1:-1], closes[-n:])]
    mean = sum(rets) / n
    return math.sqrt(sum((r - mean) ** 2 for r in rets) / (n - 1)) * math.sqrt(252)


# ------------------------------------------------------------------ analysts
def technical(ctx: Context) -> Verdict:
    closes = ctx.snapshot.closes
    if len(closes) < 50:
        return Verdict("technical", ANALYST, ABSTAIN, reasons=("fewer than 50 daily closes",))
    s20, s50, last, d = sma(closes, 20), sma(closes, 50), closes[-1], ctx.direction
    r = rsi(closes)
    ev = {"sma20": round(s20, 2), "sma50": round(s50, 2), "last": round(last, 2), "rsi14": r}
    if not (d * (last - s20) > 0 and d * (s20 - s50) > 0):
        return Verdict("technical", ANALYST, OPPOSE, 0.6, ("price and trend do not line up with the option's direction",), ev)
    conf = 0.4 + 0.6 * _clamp(abs(s20 / s50 - 1) / 0.03)
    reasons = [f"20/50-day trend agrees with the {'call' if d > 0 else 'put'}"]
    ext = d * (last / s20 - 1) * 100
    ev["extension_pct"] = round(ext, 2)
    if ext > 6:
        conf *= 0.5
        reasons.append(f"extended {ext:.1f}% from the 20-day average, so chasing")
    if r is not None and ((d > 0 and r > 75) or (d < 0 and r < 25)):
        conf *= 0.6
        reasons.append(f"RSI {r} is stretched")
    return Verdict("technical", ANALYST, SUPPORT, conf, tuple(reasons), ev)


def volatility(ctx: Context) -> Verdict:
    row, rv = ctx.row, realized_vol(ctx.snapshot.closes)
    if row is None or not row.iv or row.iv <= 0 or rv is None or rv <= 0:
        return Verdict("volatility", ANALYST, ABSTAIN, reasons=("implied or realized volatility unavailable",))
    rv = max(rv, 0.08)  # a near-flat price history makes the ratio meaningless, so floor the denominator
    ratio = row.iv / rv
    ev = {"iv": round(row.iv, 3), "realized_vol": round(rv, 3), "iv_to_rv": round(ratio, 2),
          "regime": "HIGH_VOL" if rv > 0.40 else "NORMAL"}
    if ratio > 1.5:
        return Verdict("volatility", ANALYST, OPPOSE, _clamp(0.4 + (ratio - 1.5) / 2), (f"implied vol is {ratio:.1f}x realized: premium looks rich",), ev)
    if ratio < 1.0:
        return Verdict("volatility", ANALYST, SUPPORT, 0.5, (f"implied vol is {ratio:.1f}x realized: premium looks cheap",), ev)
    return Verdict("volatility", ANALYST, ABSTAIN, reasons=(f"implied vol is {ratio:.1f}x realized: no edge either way",), evidence=ev)


def sentiment(ctx: Context) -> Verdict:
    """Option-market positioning from the recorded chain. News sentiment needs a data source the owner has not chosen."""
    sig = compute_signals(ctx.snapshot, ctx.now)["values"]
    cpv = sig["call_put_volume_ratio"]
    ev = {"call_put_volume_ratio": cpv, "call_put_oi_ratio": sig["call_put_oi_ratio"], "unusual_count": sig["unusual_count"]}
    if cpv is None or cpv <= 0:
        return Verdict("sentiment", ANALYST, ABSTAIN, reasons=("no usable call/put volume ratio",), evidence=ev, experimental=True)
    lean = math.log(cpv) * ctx.direction  # positive: flow leans the same way as the candidate
    if lean > 0.18:
        return Verdict("sentiment", ANALYST, SUPPORT, _clamp(lean), (f"option volume leans the same way (call/put {cpv:.2f})",), ev, experimental=True)
    if lean < -0.18:
        return Verdict("sentiment", ANALYST, OPPOSE, _clamp(-lean), (f"option volume leans against it (call/put {cpv:.2f})",), ev, experimental=True)
    return Verdict("sentiment", ANALYST, ABSTAIN, reasons=("option volume is balanced",), evidence=ev, experimental=True)


# ------------------------------------------------------------------ gates and the skeptic
def execution(ctx: Context) -> Verdict:
    row = ctx.row
    if row is None or row.bid <= 0 or row.ask <= 0 or row.bid > row.ask:
        return Verdict("execution", GATE, OPPOSE, 1.0, ("no valid two-sided quote for this contract",), hard_veto=True)
    spread = (row.ask - row.bid) / row.ask * 100
    ev = {"spread_pct": round(spread, 2), "volume": row.volume, "open_interest": row.open_interest}
    if spread > 12:  # tighter than the risk policy's 15
        return Verdict("execution", GATE, OPPOSE, 1.0, (f"spread {spread:.1f}% of ask is too wide to trade out of",), ev, hard_veto=True)
    if row.open_interest and ctx.size_cap > 0.01 * row.open_interest:
        return Verdict("execution", GATE, OPPOSE, 0.6, ("order would be more than 1% of open interest",), ev)
    return Verdict("execution", GATE, ABSTAIN, reasons=(f"spread {spread:.1f}% is tradable",), evidence=ev)


def exposure(ctx: Context) -> Verdict:
    c = ctx.proposal.contract
    same = [p for p in ctx.positions if p.contract.underlying == c.underlying and p.contract.right is c.right]
    prem = sum(p.avg_cost * p.quantity * 100 for p in ctx.positions)
    pct = prem / ctx.account.equity * 100 if ctx.account.equity > 0 else 100.0
    ev = {"same_underlying_side": len(same), "open_premium_pct": round(pct, 2)}
    if same:
        return Verdict("exposure", GATE, OPPOSE, 1.0, (f"already hold {len(same)} {c.underlying} {c.right.value} position(s): this stacks one bet",), ev, veto=True)
    if pct > 5:
        return Verdict("exposure", GATE, OPPOSE, _clamp(pct / 10), (f"{pct:.1f}% of equity is already in open premium",), ev)
    return Verdict("exposure", GATE, ABSTAIN, reasons=("portfolio has room",), evidence=ev)


EARNINGS_NEAR_DAYS = 5  # a report this close is mostly an implied-volatility trade, not a trend trade
FOMC_NEAR_DAYS = 1


def events(ctx: Context) -> Verdict:
    """Earnings and FOMC decisions. Unknown earnings for a single stock is a hard veto: fail closed."""
    ev = ctx.events
    if ev is None:
        return Verdict("events", GATE, OPPOSE, 1.0, ("no event calendar was consulted",), hard_veto=True)
    today = ctx.now.date()
    evidence: dict[str, Any] = {"is_etf": ev.is_etf, "earnings": [e.to_dict() for e in ev.earnings or []],
                                "fomc": [e.to_dict() for e in ev.macro or []][:3]}
    if ev.earnings is None:
        return Verdict("events", GATE, OPPOSE, 1.0, ("earnings date unknown for a single stock: a report can gap the price and crush implied volatility",),
                       evidence, hard_veto=True)
    reasons: list[str] = []
    veto, conf = False, 0.0
    if ev.earnings:
        nxt = min(ev.earnings, key=lambda e: e.day)
        days = (nxt.day - today).days
        evidence["days_to_earnings"] = days
        if days <= EARNINGS_NEAR_DAYS:
            return Verdict("events", GATE, OPPOSE, 1.0, (f"earnings in {days} day(s): implied-volatility crush and gap risk",), evidence, veto=True)
        conf = 0.3
        reasons.append(f"earnings in {days} days fall inside this option's life")
    if ev.macro is None:
        reasons.append("FOMC calendar does not cover these dates")
    else:
        soon = [e for e in ev.macro if 0 <= (e.day - today).days <= FOMC_NEAR_DAYS]
        if soon:
            conf = max(conf, 0.4)
            reasons.append(f"FOMC decision on {soon[0].day.isoformat()}" + (" (tentative)" if soon[0].tentative else ""))
    if conf > 0:
        return Verdict("events", GATE, OPPOSE, conf, tuple(reasons), evidence)
    return Verdict("events", GATE, ABSTAIN, reasons=tuple(reasons) or ("no scheduled earnings or FOMC decision in the way",), evidence=evidence)


def skeptic(ctx: Context) -> Verdict:
    """Always argues against. Lists every objection, ranked; only a blocking one vetoes."""
    objections: list[tuple[str, str]] = []  # (severity, text)
    row, p, c = ctx.row, ctx.proposal, ctx.proposal.contract
    ev: dict[str, Any] = {}
    if row is not None and row.iv and row.iv > 0 and ctx.snapshot.underlying > 0 and ctx.dte > 0:
        be = c.strike + p.limit_price if c.right is Right.CALL else c.strike - p.limit_price
        need = max(0.0, ctx.direction * (be / ctx.snapshot.underlying - 1) * 100)
        sd = row.iv * math.sqrt(ctx.dte / 365) * 100
        ev.update(breakeven_move_pct=round(need, 2), one_sd_move_pct=round(sd, 2))
        if need > 1.6 * sd:
            objections.append(("blocking", f"breakeven needs a {need:.1f}% move, {need / sd:.1f}x what the market implies"))
        elif need > 1.0 * sd:
            objections.append(("major", f"breakeven needs a {need:.1f}% move, beyond one implied standard deviation ({sd:.1f}%)"))
    else:
        objections.append(("major", "cannot test breakeven against implied move: IV or DTE missing"))
    if row is not None and row.ask > 0:
        spread = (row.ask - row.bid) / row.ask * 100
        if spread * 3 >= ctx.stop_loss_pct:
            objections.append(("major", f"spread {spread:.1f}% eats a third of the {ctx.stop_loss_pct:.0f}% stop distance"))
    if ctx.dte < ctx.policy.min_dte:
        objections.append(("blocking", f"{ctx.dte} days to expiry is inside the risk policy minimum"))
    if (ctx.now - ctx.snapshot.as_of).total_seconds() > 900:
        objections.append(("blocking", "the snapshot is more than 15 minutes old"))
    if not ctx.snapshot.timestamp_verified:
        objections.append(("minor", "quote times are download times, not exchange times"))
    if ctx.events is None:
        objections.append(("major", "no event calendar was consulted: earnings and FOMC dates are unchecked"))
    else:
        objections.append(("minor", "CPI, jobs data, dividends and company news are not checked"))
        if ctx.events.macro is None:
            objections.append(("minor", "the FOMC table does not cover these dates"))
    objections.append(("minor", "the baseline strategy has no demonstrated edge"))
    rank = {"blocking": 0, "major": 1, "minor": 2}
    objections.sort(key=lambda o: rank[o[0]])
    blocking = [t for s, t in objections if s == "blocking"]
    major = [t for s, t in objections if s == "major"]
    conf = _clamp(0.6 * len(blocking) + 0.3 * len(major) + 0.05 * (len(objections) - len(blocking) - len(major)))
    ev["objections"] = [{"severity": s, "text": t} for s, t in objections]
    stance = OPPOSE if (blocking or major) else ABSTAIN
    return Verdict("skeptic", SKEPTIC, stance, conf, tuple(t for _, t in objections[:3]), ev, veto=bool(blocking))


ANALYSTS = (technical, volatility, sentiment)
CHECKERS = (execution, exposure, events, skeptic)


def run_agent(fn: Any, ctx: Context) -> Verdict:
    """An agent that crashes abstains (analyst) or hard-vetoes (gate or skeptic): failing means no trade."""
    try:
        return fn(ctx)
    except Exception as exc:  # noqa: BLE001
        name = getattr(fn, "__name__", "agent")
        role = ANALYST if fn in ANALYSTS else GATE
        reason = f"agent error: {type(exc).__name__}"
        if role == ANALYST:
            return Verdict(name, role, ABSTAIN, reasons=(reason,))
        return Verdict(name, role, OPPOSE, 1.0, (reason,), hard_veto=True)
