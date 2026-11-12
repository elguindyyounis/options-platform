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
                        "bid": row.bid,
                        "ask": row.ask,
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
