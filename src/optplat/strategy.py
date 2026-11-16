"""Strategy interface plus a deliberately simple BASELINE.

``LiquidTrendStrategy`` exists to exercise the pipeline end to end. It has no demonstrated edge.
Treat any strategy as unproven until it survives out-of-sample, cost-aware testing.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from .marketdata import MarketSnapshot
from .models import OptionContract, Right
from .pricing import buy_limit_for


@dataclass(frozen=True)
class Proposal:
    contract: OptionContract
    limit_price: float
    score: float  # ranking heuristic only; not a probability of profit
    rationale: dict[str, Any]


class Strategy(ABC):
    name: str = "abstract"
    version: str = "0"

    @abstractmethod
    def propose(self, snapshot: MarketSnapshot, now: datetime) -> list[Proposal]:
        """Return candidate buys, best first. Proposals are suggestions; risk still decides."""


class LiquidTrendStrategy(Strategy):
    """Follow a clear 20/50-day trend with a liquid, near-the-money, mid-dated option."""

    name = "liquid-trend"
    version = "0.1.0"

    def __init__(
        self,
        *,
        min_dte: int = 30,
        max_dte: int = 120,
        max_moneyness_pct: float = 5.0,
        max_spread_pct: float = 10.0,
        min_volume: int = 50,
        min_open_interest: int = 500,
    ) -> None:
        self.min_dte = min_dte
        self.max_dte = max_dte
        self.max_moneyness_pct = max_moneyness_pct
        self.max_spread_pct = max_spread_pct
        self.min_volume = min_volume
        self.min_open_interest = min_open_interest

    def explain_no_proposal(self, snapshot: MarketSnapshot, now: datetime) -> str:
        """Plain-language reason `propose` found nothing. Display only; never used to trade."""
        closes = snapshot.closes
        if len(closes) < 50 or snapshot.underlying <= 0:
            return "Fewer than 50 daily closes, so no trend can be measured."
        sma20 = sum(closes[-20:]) / 20
        sma50 = sum(closes[-50:]) / 50
        last = closes[-1]
        if last > sma20 > sma50:
            right = Right.CALL
        elif last < sma20 < sma50:
            right = Right.PUT
        else:
            return "No clear trend (price, 20-day and 50-day averages are not lined up), so no trade."
        counts = {"expiry": 0, "quote": 0, "spread": 0, "liquidity_missing": 0, "liquidity": 0, "strike": 0}
        for row in snapshot.rows:
            c = row.contract
            if c.right is not right:
                continue
            if not self.min_dte <= (c.expiry - now.date()).days <= self.max_dte:
                counts["expiry"] += 1
            elif row.bid <= 0 or row.ask <= 0 or row.bid > row.ask:
                counts["quote"] += 1
            elif (row.ask - row.bid) / row.ask * 100 > self.max_spread_pct:
                counts["spread"] += 1
            elif row.volume is None or row.open_interest is None:
                # Display only: propose() still rejects these (None counts as 0), but the reason differs.
                counts["liquidity_missing"] += 1
            elif row.volume < self.min_volume or row.open_interest < self.min_open_interest:
                counts["liquidity"] += 1
            elif abs(c.strike / snapshot.underlying - 1) * 100 > self.max_moneyness_pct:
                counts["strike"] += 1
        label = {
            "expiry": "expiry outside the allowed window",
            "quote": "no usable bid/ask",
            "spread": "bid/ask spread too wide",
            "liquidity_missing": "volume or open interest not reported by the data provider (treated as failing)",
            "liquidity": "volume or open interest too low",
            "strike": "strike too far from the price",
        }
        trend = "up" if right is Right.CALL else "down"
        parts = [f"{n} {label[k]}" for k, n in counts.items() if n]
        if not parts:
            return f"Trend is {trend} but the snapshot has no {right.name.lower()} contracts to consider."
        return f"Trend is {trend}, but every {right.name.lower()} contract failed: " + "; ".join(parts) + "."

    def propose(self, snapshot: MarketSnapshot, now: datetime) -> list[Proposal]:
        closes = snapshot.closes
        if len(closes) < 50 or snapshot.underlying <= 0:
            return []
        sma20 = sum(closes[-20:]) / 20
        sma50 = sum(closes[-50:]) / 50
        last = closes[-1]
        if last > sma20 > sma50:
            right, trend = Right.CALL, "UP"
        elif last < sma20 < sma50:
            right, trend = Right.PUT, "DOWN"
        else:
            return []

        out: list[Proposal] = []
        for row in snapshot.rows:
            c = row.contract
            if c.right is not right:
                continue
            dte = (c.expiry - now.date()).days
            if not self.min_dte <= dte <= self.max_dte:
                continue
            if row.bid <= 0 or row.ask <= 0 or row.bid > row.ask:
                continue
            spread = (row.ask - row.bid) / row.ask * 100
            if spread > self.max_spread_pct:
                continue
            if (row.volume or 0) < self.min_volume or (row.open_interest or 0) < self.min_open_interest:
                continue
            moneyness = abs(c.strike / snapshot.underlying - 1) * 100
            if moneyness > self.max_moneyness_pct:
                continue
            score = round(100 - spread * 2 - moneyness + min(row.open_interest or 0, 5000) / 500, 2)
            out.append(
                Proposal(
                    contract=c,
                    limit_price=buy_limit_for(row.ask),
                    score=score,
                    rationale={
                        "strategy": f"{self.name} {self.version}",
                        "trend": trend,
                        "sma20": round(sma20, 2),
                        "sma50": round(sma50, 2),
                        "spread_pct": round(spread, 2),
                        "volume": row.volume,
                        "open_interest": row.open_interest,
                        "dte": dte,
                        "moneyness_pct": round(moneyness, 2),
                        "note": "Baseline strategy with no demonstrated edge",
                    },
                )
            )
        out.sort(key=lambda p: (-p.score, p.contract.occ_symbol))
        return out


class FlowFollowStrategy(Strategy):
    """Follow unusual single-contract turnover with an OUT-of-the-money option (owner request, 2026-11-16).

    ``mode="flagged"`` buys the flagged contract itself (typically far out of the money).
    ``mode="nearer"`` buys the same side and expiry but a strike closer to the money, around
    ``nearer_target_otm_pct``, which is usually more liquid and less of a lottery ticket.
    The trigger is volume far above open interest at large premium. A free chain cannot show who
    bought or whether the trade opened a position, so the flow may be a hedge: direction is an
    ASSUMPTION, not evidence. No demonstrated edge. Defaults match the platform risk gate (7+ days,
    spread 15% or less), so proposals are not pre-rejected; the risk policy itself is untouched.
    """

    version = "0.1.0"

    def __init__(
        self,
        *,
        mode: str = "flagged",
        min_dte: int = 7,
        max_dte: int = 30,
        min_premium_usd: float = 100_000.0,
        min_ask: float = 0.05,
        max_spread_pct: float = 15.0,
        nearer_target_otm_pct: float = 8.0,
        nearer_min_volume: int = 100,
        nearer_min_open_interest: int = 100,
    ) -> None:
        if mode not in ("flagged", "nearer"):
            raise ValueError("mode must be 'flagged' or 'nearer'")
        self.mode = mode
        self.name = "flow-otm" if mode == "flagged" else "flow-near"
        self.min_dte, self.max_dte = min_dte, max_dte
        self.min_premium_usd, self.min_ask = min_premium_usd, min_ask
        self.max_spread_pct = max_spread_pct
        self.nearer_target_otm_pct = nearer_target_otm_pct
        self.nearer_min_volume, self.nearer_min_open_interest = nearer_min_volume, nearer_min_open_interest

    @staticmethod
    def _otm(snapshot: MarketSnapshot, c: OptionContract) -> float:
        raw = (snapshot.underlying - c.strike) if c.right is Right.PUT else (c.strike - snapshot.underlying)
        return max(0.0, raw) / snapshot.underlying * 100

    def _ok_quote(self, row: Any) -> bool:
        return row.bid > 0 and row.ask >= self.min_ask and row.bid <= row.ask and (row.ask - row.bid) / row.ask * 100 <= self.max_spread_pct

    def explain_no_proposal(self, snapshot: MarketSnapshot, now: datetime) -> str:
        from .flow import scan_flow

        flagged = scan_flow(snapshot)
        if not flagged:
            return "No unusual turnover (volume far above open interest) in this chain, so nothing to follow."
        return (
            f"{len(flagged)} unusual-turnover contract(s) found, but none passed: premium at least "
            f"${self.min_premium_usd:,.0f}, {self.min_dte}-{self.max_dte} days to expiry, an out-of-the-money strike, and a usable quote."
        )

    def propose(self, snapshot: MarketSnapshot, now: datetime) -> list[Proposal]:
        from .flow import scan_flow

        if snapshot.underlying <= 0:
            return []
        rows = {(r.contract.expiry, r.contract.right, r.contract.strike): r for r in snapshot.rows}
        out: list[Proposal] = []
        for f in scan_flow(snapshot):
            if f["premium_at_quoted_mid_usd"] is None or f["premium_at_quoted_mid_usd"] < self.min_premium_usd:
                continue
            if not self.min_dte <= f["dte"] <= self.max_dte or not f["otm_pct"]:
                continue  # at or in the money is not what this strategy is for
            right = Right(f["right"])
            expiry = now.date().__class__.fromisoformat(f["expiry"])
            pick = rows.get((expiry, right, f["strike"]))
            if self.mode == "nearer":
                cands = [
                    r for k, r in rows.items()
                    if k[0] == expiry and k[1] is right and self._otm(snapshot, r.contract) > 0
                    and self._ok_quote(r) and (r.volume or 0) >= self.nearer_min_volume
                    and (r.open_interest or 0) >= self.nearer_min_open_interest
                    and self._otm(snapshot, r.contract) < f["otm_pct"]
                ]
                pick = min(cands, key=lambda r: (abs(self._otm(snapshot, r.contract) - self.nearer_target_otm_pct), r.contract.strike), default=None)
            if pick is None or not self._ok_quote(pick):
                continue
            spread = (pick.ask - pick.bid) / pick.ask * 100
            otm = self._otm(snapshot, pick.contract)
            out.append(
                Proposal(
                    contract=pick.contract,
                    limit_price=buy_limit_for(pick.ask),
                    score=round({"EXTREME": 90, "HIGH": 70, "ELEVATED": 50}[f["tier"]] - spread, 2),
                    rationale={
                        "strategy": f"{self.name} {self.version}",
                        "trend": f"flow {f['right']}",
                        "flagged_contract": f["contract"],
                        "flagged_volume_oi_ratio": f["volume_oi_ratio"],
                        "flagged_premium_at_mid_usd": f["premium_at_quoted_mid_usd"],
                        "spread_pct": round(spread, 2),
                        "volume": pick.volume,
                        "open_interest": pick.open_interest,
                        "dte": f["dte"],
                        "otm_pct": round(otm, 1),
                        "note": "Follows unusual turnover; direction unverified (may be a hedge). No demonstrated edge.",
                    },
                )
            )
        out.sort(key=lambda p: (-p.score, p.contract.occ_symbol))
        return out
