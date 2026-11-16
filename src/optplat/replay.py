"""Replay recorded market snapshots through the real engine, deterministically.

The replay runs in a throwaway in-memory store with a simulated broker and a fake clock. It never writes
to the database the snapshots came from, never records snapshots again, and never looks ahead: at each
step it only sees snapshots recorded at or before that step's time. It is a plumbing test for history,
not evidence of an edge: fills are simulated and recorded data is delayed and incomplete.
"""
from __future__ import annotations

import bisect
import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Optional, Sequence

from .broker.sim import SimBroker
from .engine import TradingEngine
from .marketdata import MarketDataProvider, MarketSnapshot, snapshot_from_dict
from .models import OptionContract, Quote
from .orders import OrderManager
from .risk import RiskPolicy
from .store import Store
from .strategy import LiquidTrendStrategy, Strategy


class ReplayClock:
    """A clock that only moves when the replay moves it."""

    def __init__(self, start: datetime) -> None:
        self.now = start

    def __call__(self) -> datetime:
        return self.now


class ReplayDataProvider(MarketDataProvider):
    """Serves recorded snapshots as they looked at the replay clock's time (never later)."""

    name = "replay"

    def __init__(self, rows: Sequence[dict[str, Any]], clock: Callable[[], datetime]) -> None:
        """`rows` are dicts as returned by `Store.list_snapshots` (recorded_at, fictional, payload)."""
        if not rows:
            raise ValueError("No recorded snapshots to replay")
        flags = {bool(r["fictional"]) for r in rows}
        if len(flags) > 1:
            raise ValueError("Refusing to replay real and fictional snapshots together")
        self.fictional = flags.pop()
        self._clock = clock
        by_symbol: dict[str, list[tuple[datetime, int, MarketSnapshot]]] = {}
        for r in rows:
            at = datetime.fromisoformat(r["recorded_at"])
            by_symbol.setdefault(r["symbol"], []).append((at, int(r.get("id", 0)), snapshot_from_dict(r["payload"])))
        self._times: dict[str, list[datetime]] = {}
        self._snaps: dict[str, list[MarketSnapshot]] = {}
        for symbol, items in by_symbol.items():
            items.sort(key=lambda t: (t[0], t[1]))
            self._times[symbol] = [t[0] for t in items]
            self._snaps[symbol] = [t[2] for t in items]
        self._steps = sorted({t for times in self._times.values() for t in times})

    def steps(self) -> list[datetime]:
        """Every distinct moment something was recorded, oldest first."""
        return list(self._steps)

    def symbols(self) -> list[str]:
        return sorted(self._snaps)

    def _latest(self, symbol: str) -> Optional[MarketSnapshot]:
        times = self._times.get(symbol)
        if not times:
            return None
        i = bisect.bisect_right(times, self._clock())
        return self._snaps[symbol][i - 1] if i else None

    def snapshot(self, symbol: str) -> MarketSnapshot:
        snap = self._latest(symbol)
        if snap is None:
            raise RuntimeError(f"No recorded snapshot for {symbol} at or before {self._clock().isoformat()}")
        return snap

    def quotes_for(self, contracts: Sequence[OptionContract]) -> list[Quote]:
        wanted = set(contracts)
        quotes: list[Quote] = []
        for symbol in self._snaps:
            snap = self._latest(symbol)
            if snap is None:
                continue
            quotes.extend(
                r.to_quote(snap.as_of, snap.source, snap.timestamp_verified) for r in snap.rows if r.contract in wanted
            )
        return quotes


def _without_random_ids(value: Any) -> Any:
    """Order ids are random UUIDs; everything else in a replay is deterministic."""
    if isinstance(value, dict):
        return {k: _without_random_ids(v) for k, v in value.items() if k != "order_id"}
    if isinstance(value, list):
        return [_without_random_ids(v) for v in value]
    return value


@dataclass
class ReplayResult:
    steps: int
    cycles: list[dict[str, Any]] = field(default_factory=list)
    trace: list[list[Any]] = field(default_factory=list)  # per step: [time, [[kind, contract, result], ...]]
    equity: list[float] = field(default_factory=list)  # account equity after each step (open positions at bid)
    report: dict[str, Any] = field(default_factory=dict)  # OrderManager.report(): realized P&L and open positions
    fictional: bool = False

    def fingerprint(self) -> str:
        """Stable hash of what happened. Two replays of the same rows must give the same value."""
        blob = json.dumps({"trace": self.trace, "equity": self.equity, "report": _without_random_ids(self.report)}, sort_keys=True, default=str)
        return hashlib.sha256(blob.encode()).hexdigest()


def run_replay(
    rows: Sequence[dict[str, Any]],
    *,
    strategy: Optional[Strategy] = None,
    config: Optional[dict[str, Any]] = None,
    policy: Optional[RiskPolicy] = None,
) -> ReplayResult:
    """Run one engine cycle per recorded moment, in order.

    `policy` defaults to the strict `RiskPolicy()`: recorded Yahoo quotes have no verified timestamp, so
    they are rejected unless the caller passes the same explicit opt-in used live. `config` is applied to a
    fresh engine config (watchlist defaults to every recorded symbol; entries stay off unless asked for).
    """
    clock = ReplayClock(datetime.fromisoformat(min(r["recorded_at"] for r in rows)))
    provider = ReplayDataProvider(rows, clock)
    store = Store(":memory:")  # throwaway: the source database is never touched
    manager = OrderManager(SimBroker(), store, policy or RiskPolicy(), clock=clock)
    engine = TradingEngine(manager, provider, strategy or LiquidTrendStrategy(), clock=clock)
    engine.set_config({"watchlist": provider.symbols(), **(config or {}), "record_snapshots": False})

    result = ReplayResult(steps=0, fictional=provider.fictional)
    for moment in provider.steps():
        clock.now = moment
        cycle = engine.run_cycle()
        result.steps += 1
        result.cycles.append(cycle)
        items = [["exit", x.get("contract"), x.get("result") or x.get("action")] for x in cycle["exits"]]
        items += [["entry", x.get("contract") or x.get("symbol"), x.get("result")] for x in cycle["entries"]]
        result.trace.append([moment.isoformat(), items])
        result.equity.append(manager.broker.get_account().equity)
    result.report = manager.report()
    return result
