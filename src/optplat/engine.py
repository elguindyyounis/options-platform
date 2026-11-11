"""The trading cycle: reconcile -> cancel stale orders -> manage exits -> (optionally) open entries.

Safety rules baked in:
* Automatic entries can never be on while automatic exits are off.
* Entries pause when the market is closed, the kill switch is on, any held position cannot be
  priced, or any order is unresolved. Exits are never blocked by the kill switch.
* Every order carries a deterministic idempotency key, so a repeated cycle cannot double-submit.
"""
from __future__ import annotations

import json
import math
import re
import threading
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from typing import Any, Callable, Optional

from . import committee as cmt
from .agents import Context
from .broker.sim import SimBroker
from .exits import EXIT, UNOBSERVABLE, ExitPolicy, evaluate_exit
from .market_clock import session_status
from .dataquality import check_snapshot, frozen_issue, quote_fingerprint
from .marketdata import MarketDataProvider, MarketSnapshot, snapshot_to_dict
from .models import Account, OrderIntent, OrderState, Position, Side, utcnow
from .orders import OrderManager
from .pricing import sell_limit_for
from .risk import RiskPolicy
from .strategy import Strategy

SYMBOL_RE = re.compile(r"^[A-Z][A-Z0-9.\-]{0,9}$")


@dataclass(frozen=True)
class EngineConfig:
    watchlist: tuple[str, ...] = ("SPY", "QQQ")
    auto_entries: bool = False  # OFF by default
    auto_exits: bool = True
    max_new_per_cycle: int = 1
    order_ttl_s: int = 900
    interval_s: int = 300
    enforce_market_hours: bool = True
    take_profit_pct: float = 40.0
    stop_loss_pct: float = 30.0
    max_days_held: int = 0
    min_dte_to_hold: int = 5
    reentry_cooldown_s: int = 86400  # do not re-buy a contract within this long of selling it
    record_snapshots: bool = True  # keep every observed snapshot: the raw material for honest replay
    snapshot_retention_days: int = 30
    committee_mode: str = "shadow"  # off | shadow (records its votes only) | active (its vote and size apply)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["watchlist"] = list(self.watchlist)
        return d

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "EngineConfig":
        base = cls()
        data = {k: raw[k] for k in asdict(base) if k in raw}
        watch = data.get("watchlist", base.watchlist)
        if isinstance(watch, str):
            watch = [w for w in re.split(r"[,\s]+", watch) if w]
        symbols: list[str] = []
        for s in watch:
            s = str(s).upper().strip()
            if not SYMBOL_RE.fullmatch(s):
                raise ValueError(f"Invalid ticker: {s!r}")
            if s not in symbols:
                symbols.append(s)
        if not 1 <= len(symbols) <= 20:
            raise ValueError("Watchlist must contain 1-20 tickers")
        data["watchlist"] = tuple(symbols)
        cfg = cls(**data)
        cfg._validate()
        return cfg

    def _validate(self) -> None:
        for name, value in asdict(self).items():
            if name == "watchlist":
                continue
            if isinstance(value, bool) != (name in ("auto_entries", "auto_exits", "enforce_market_hours", "record_snapshots")):
                raise ValueError(f"{name} has the wrong type")
        checks = [
            (0 <= self.max_new_per_cycle <= 5, "max_new_per_cycle must be 0-5"),
            (60 <= self.order_ttl_s <= 3600, "order_ttl_s must be 60-3600"),
            (30 <= self.interval_s <= 3600, "interval_s must be 30-3600"),
            (1 <= self.take_profit_pct <= 1000, "take_profit_pct must be 1-1000"),
            (1 <= self.stop_loss_pct <= 95, "stop_loss_pct must be 1-95"),
            (0 <= self.max_days_held <= 365, "max_days_held must be 0-365"),
            (0 <= self.min_dte_to_hold <= 60, "min_dte_to_hold must be 0-60"),
            (0 <= self.reentry_cooldown_s <= 2_592_000, "reentry_cooldown_s must be 0-2592000"),
            (1 <= self.snapshot_retention_days <= 3650, "snapshot_retention_days must be 1-3650"),
            (self.committee_mode in ("off", "shadow", "active"), "committee_mode must be off, shadow or active"),
        ]
        for ok, message in checks:
            if not ok:
                raise ValueError(message)
        if self.auto_entries and not self.auto_exits:
            raise ValueError("auto_entries requires auto_exits: never open positions you will not manage")


def size_quantity(account: Account, policy: RiskPolicy, limit_price: float) -> int:
    """Largest whole quantity whose worst-case cost fits the per-position cap and available cash."""
    if not (math.isfinite(limit_price) and limit_price > 0 and account.equity > 0):
        return 0
    budget = min(account.equity * policy.max_position_pct / 100, account.cash)
    return max(0, min(policy.max_quantity, math.floor(budget / (limit_price * 100) + 1e-9)))


class TradingEngine:
    def __init__(
        self,
        manager: OrderManager,
        provider: MarketDataProvider,
        strategy: Strategy,
        *,
        clock: Callable[[], datetime] = utcnow,
        default_config: Optional[EngineConfig] = None,
    ) -> None:
        self.manager = manager
        self.provider = provider
        self.strategy = strategy
        self.store = manager.store
        self.clock = clock
        self._default = default_config or EngineConfig()
        self._lock = threading.RLock()
        self._cycle_cfg: EngineConfig = self._default
        self._cycle_now: datetime = self.clock()
        self._cycle_market_open: bool = False
        self._journal_seen: dict[tuple[str, str, str], datetime] = {}
        self._last_fingerprint: dict[str, tuple[str, int]] = {}

    # ---- config -------------------------------------------------------
    def config(self) -> EngineConfig:
        raw = self.store.get_state("engine_config", "")
        if not raw:
            return self._default
        try:
            return EngineConfig.from_dict(json.loads(raw))
        except (ValueError, TypeError):
            return self._default  # corrupt or invalid settings fall back to the safe defaults

    def set_config(self, changes: dict[str, Any]) -> EngineConfig:
        merged = {**self.config().to_dict(), **changes}
        new = EngineConfig.from_dict(merged)  # validates
        self.store.set_state("engine_config", json.dumps(new.to_dict()))
        self.store.audit("engine_config", None, {"changes": changes})
        return new

    def _hours_enforced(self, cfg: EngineConfig) -> bool:
        """Market hours can only be switched off for fictional data. Real quotes outside the session are stale."""
        return cfg.enforce_market_hours or not self.provider.fictional

    def last_cycle(self) -> Optional[dict[str, Any]]:
        raw = self.store.get_state("last_cycle", "")
        return json.loads(raw) if raw else None

    def status(self) -> dict[str, Any]:
        is_open, reason = session_status(self.clock())
        return {
            "config": self.config().to_dict(),
            "market": {"open": is_open, "reason": reason, "hours_enforced": self._hours_enforced(self.config())},
            "data_source": {"name": self.provider.name, "fictional": self.provider.fictional},
            "strategy": {"name": self.strategy.name, "version": self.strategy.version},
            "kill_switch": self.manager.kill_switch_active(),
            "last_cycle": self.last_cycle(),
            "recorder": self.store.snapshot_stats(),
            "data_quality": {
                "window_hours": 24,
                "issues": self.store.data_issue_summary(self.clock() - timedelta(hours=24)),
            },
        }

    # ---- cycle --------------------------------------------------------
    def run_cycle(self) -> dict[str, Any]:
        with self._lock:
            now = self.clock()
            cfg = self.config()
            is_open, reason = session_status(now)
            trading_allowed = is_open or not self._hours_enforced(cfg)
            self._cycle_cfg, self._cycle_now = cfg, now
            self._cycle_market_open = is_open
            report: dict[str, Any] = {
                "started_at": now.isoformat(),
                "market_open": is_open,
                "market_reason": reason,
                "trading_allowed": trading_allowed,
                "data_source": self.provider.name,
                "fictional_data": self.provider.fictional,
                "reconciled": [],
                "cancelled_stale": [],
                "exits": [],
                "entries": [],
                "entries_note": "",
                "snapshots_recorded": 0,
                "data_quality": [],
                "errors": [],
            }
            self._guard(report, "snapshot prune", lambda: self._maybe_prune_snapshots(cfg, now))
            self._maybe_learn(cfg, now)
            snapshots: dict[str, Optional[MarketSnapshot]] = {}

            if hasattr(self.provider, "advance"):
                self.provider.advance()  # demo market moves one step per cycle

            try:
                positions = self.manager.broker.get_positions()
            except Exception as exc:  # noqa: BLE001
                report["errors"].append(f"positions: {type(exc).__name__}")
                report["entries_note"] = "Broker positions unavailable; nothing was done"
                return self._finish(report)

            self._sync_sim_quotes(cfg, positions, snapshots, report)
            self._guard(report, "reconcile", lambda: report.__setitem__("reconciled", self.manager.reconcile()))
            self._guard(report, "stale", lambda: report.__setitem__("cancelled_stale", self._cancel_stale(cfg, now)))
            try:
                positions = self.manager.broker.get_positions()
            except Exception as exc:  # noqa: BLE001
                report["errors"].append(f"positions: {type(exc).__name__}")
                return self._finish(report)

            self._guard(
                report,
                "exits",
                lambda: report.__setitem__("exits", self._run_exits(cfg, positions, trading_allowed, now)),
            )
            self._guard(
                report,
                "entries",
                lambda: self._run_entries(cfg, positions, trading_allowed, snapshots, report, now),
            )
            return self._finish(report)

    def _finish(self, report: dict[str, Any]) -> dict[str, Any]:
        report["finished_at"] = self.clock().isoformat()
        if report.get("trading_allowed"):  # equity only moves with the market; flat overnight points would stretch the chart
            try:
                acct = self.manager.broker.get_account()
                self.store.record_equity(self._cycle_now, acct.equity, acct.cash, acct.open_premium, self.provider.fictional)
            except Exception:  # noqa: BLE001 - a missing chart point must never affect a cycle
                pass
        self.store.set_state("last_cycle", json.dumps(report, default=str))
        self.store.audit("engine_cycle", None, {"exits": len(report["exits"]), "entries": len(report["entries"])})
        return report

    @staticmethod
    def _guard(report: dict[str, Any], phase: str, fn: Callable[[], Any]) -> None:
        try:
            fn()
        except Exception as exc:  # noqa: BLE001 - one failing phase must not stop the others
            report["errors"].append(f"{phase}: {type(exc).__name__}: {str(exc)[:120]}")

    # ---- phases -------------------------------------------------------
    def _snapshot(
        self, symbol: str, cache: dict[str, Optional[MarketSnapshot]], report: dict[str, Any]
    ) -> Optional[MarketSnapshot]:
        if symbol not in cache:
            try:
                cache[symbol] = self.provider.snapshot(symbol)
            except Exception as exc:  # noqa: BLE001
                cache[symbol] = None
                report["errors"].append(f"data {symbol}: {type(exc).__name__}: {str(exc)[:100]}")
            else:
                self._record(cache[symbol], report)  # the raw snapshot is kept as the provider returned it
                cache[symbol] = self._vet(cache[symbol], report)
        return cache[symbol]

    JOURNAL_DEDUPE_S = 3600
    JOURNAL_MAX_CANDIDATES = 5
    _ALWAYS_JOURNAL = {"FILLED", "SUBMITTED", "PARTIALLY_FILLED", "RISK_REJECTED", "BROKER_REJECTED"}

    def _journal(
        self,
        kind: str,
        symbol: str,
        disposition: str,
        contract: Any,
        ref_price: Optional[float],
        payload: dict[str, Any],
        snap: Optional[MarketSnapshot] = None,
        order_id: Optional[str] = None,
    ) -> None:
        """Append one decision record. Repeats of the same contract/disposition within an hour are not re-written
        (a candidate that stays on screen every cycle would otherwise flood the journal). Never blocks trading."""
        try:
            key = (contract.occ_symbol.strip(), kind, disposition)
            last = self._journal_seen.get(key)
            if disposition not in self._ALWAYS_JOURNAL and last is not None and (
                self._cycle_now - last
            ).total_seconds() < self.JOURNAL_DEDUPE_S:
                return
            self._journal_seen[key] = self._cycle_now
            provenance = {
                "data_source": self.provider.name,
                "snapshot_source": snap.source if snap else None,
                "quote_time_verified": snap.timestamp_verified if snap else None,
                "broker": self.manager.broker.name,
            }
            assumptions = ["Fills are simulated; the strategy has no demonstrated edge."]
            if snap is not None and not snap.timestamp_verified:
                assumptions.append("Quote times are unverified (download time, not exchange time).")
            self.store.record_decision(
                self._cycle_now, symbol, kind, disposition, contract.occ_symbol.strip(),
                f"{self.strategy.name}:{self.strategy.version}", ref_price, order_id,
                self.provider.fictional, {**payload, "contract": contract.to_dict(), "provenance": provenance,
                                          "assumptions": assumptions},
            )
        except Exception:  # noqa: BLE001 - the journal must never stop a cycle
            pass

    def _vet(self, snap: MarketSnapshot, report: dict[str, Any]) -> Optional[MarketSnapshot]:
        """Run the data-quality gate. A rejected snapshot is treated exactly like a failed data fetch."""
        result = check_snapshot(snap, self._cycle_now)
        issues = list(result.issues)
        fp = quote_fingerprint(snap)
        prev, n = self._last_fingerprint.get(snap.symbol, ("", 0))
        n = n + 1 if fp == prev else 0
        self._last_fingerprint[snap.symbol] = (fp, n)
        frozen = frozen_issue(n, self._cycle_market_open)
        if frozen:
            issues.append(frozen)
        for issue in issues:
            report["data_quality"].append(
                {"symbol": snap.symbol, "kind": issue.kind, "severity": issue.severity, "count": issue.count}
            )
            try:
                self.store.record_data_issue(self._cycle_now, snap.symbol, issue.kind, issue.severity, issue.count, issue.detail)
            except Exception as exc:  # noqa: BLE001 - logging trouble must not hide the data problem
                report["errors"].append(f"data issue log: {type(exc).__name__}")
        if result.rejected:
            reason = next(i for i in issues if i.severity == "reject")
            report["errors"].append(f"data {snap.symbol}: rejected ({reason.kind}: {reason.detail})")
        return result.snapshot

    def _record(self, snap: MarketSnapshot, report: dict[str, Any]) -> None:
        """Keep what the market looked like. A recording failure is reported but never blocks trading logic."""
        if not self._cycle_cfg.record_snapshots:
            return
        try:
            self.store.record_snapshot(
                snap.symbol,
                self._cycle_now,
                snap.as_of,
                snap.source,
                snap.fictional or self.provider.fictional,
                snap.timestamp_verified,
                snapshot_to_dict(snap),
            )
            report["snapshots_recorded"] += 1
        except Exception as exc:  # noqa: BLE001
            report["errors"].append(f"record {snap.symbol}: {type(exc).__name__}: {str(exc)[:100]}")

    def _committee_votes(self, cfg: EngineConfig, symbol: str, snap: MarketSnapshot, proposals: list[Any],
                         positions: list[Position], account: Account, now: datetime) -> dict[Any, cmt.CommitteeDecision]:
        """Ask the committee about the top candidates and journal every verdict. In shadow mode that is all it does."""
        if cfg.committee_mode == "off":
            return {}
        votes: dict[Any, cmt.CommitteeDecision] = {}
        try:
            weights, trust = cmt.current(self.store, self.provider.fictional)
        except Exception:  # noqa: BLE001
            return {}
        for p in proposals[: self.JOURNAL_MAX_CANDIDATES]:
            cap = size_quantity(account, self.manager.policy, p.limit_price)
            if cap < 1:
                continue
            try:
                ctx = Context(snap, p, now, account, self.manager.policy, tuple(positions), cap,
                              cfg.min_dte_to_hold, cfg.stop_loss_pct)
                d = cmt.decide(ctx, weights, trust)
            except Exception:  # noqa: BLE001 - no decision: shadow ignores it, active mode refuses the candidate
                continue
            votes[p.contract] = d
            self._journal(cmt.KIND, symbol, d.disposition, p.contract, p.limit_price, d.to_payload(weights, trust), snap)
        return votes

    def _maybe_learn(self, cfg: EngineConfig, now: datetime) -> None:
        """Refit agent weights and committee trust from matured outcomes, at most every 30 minutes."""
        if cfg.committee_mode == "off":
            return
        try:
            last = self.store.get_state("committee_last_learn", "")
            if last and now - datetime.fromisoformat(last) < timedelta(minutes=30):
                return
            cmt.learn(self.store, now, self.provider.fictional)
            self.store.set_state("committee_last_learn", now.isoformat())
        except Exception:  # noqa: BLE001 - learning must never stop a cycle
            pass

    def _maybe_prune_snapshots(self, cfg: EngineConfig, now: datetime) -> None:
        """Delete snapshots older than the retention window, at most once an hour."""
        last = self.store.get_state("snapshot_last_prune", "")
        if last and now - datetime.fromisoformat(last) < timedelta(hours=1):
            return
        self.store.prune_snapshots(now - timedelta(days=cfg.snapshot_retention_days))
        self.store.prune_data_issues(now - timedelta(days=cfg.snapshot_retention_days))
        self.store.prune_equity(now - timedelta(days=max(cfg.snapshot_retention_days, 90)))
        self.store.set_state("snapshot_last_prune", now.isoformat())

    def _sync_sim_quotes(
        self,
        cfg: EngineConfig,
        positions: list[Position],
        cache: dict[str, Optional[MarketSnapshot]],
        report: dict[str, Any],
    ) -> None:
        """With the simulated broker, its quotes come from the data provider. Real brokers quote for themselves."""
        sim = self.manager.broker
        if not isinstance(sim, SimBroker):
            return
        covered = set()
        for symbol in cfg.watchlist:
            snap = self._snapshot(symbol, cache, report)
            if snap is None:
                continue
            for row in snap.rows:
                sim.set_quote(row.to_quote(snap.as_of, snap.source, snap.timestamp_verified))
                covered.add(row.contract)
        missing = [p.contract for p in positions if p.contract not in covered]
        if missing:
            try:
                for quote in self.provider.quotes_for(missing):
                    sim.set_quote(quote)
            except Exception as exc:  # noqa: BLE001
                report["errors"].append(f"held quotes: {type(exc).__name__}: {str(exc)[:100]}")

    def _cancel_stale(self, cfg: EngineConfig, now: datetime) -> list[str]:
        cancelled = []
        ttl = timedelta(seconds=cfg.order_ttl_s)
        for order in self.manager.list(open_only=True):
            if order.state in (OrderState.SUBMITTED, OrderState.PARTIALLY_FILLED) and now - order.updated_at > ttl:
                self.manager.cancel(order.id)
                cancelled.append(order.id)
        return cancelled

    def _run_exits(
        self, cfg: EngineConfig, positions: list[Position], trading_allowed: bool, now: datetime
    ) -> list[dict[str, Any]]:
        policy = ExitPolicy(
            take_profit_pct=cfg.take_profit_pct,
            stop_loss_pct=cfg.stop_loss_pct,
            max_days_held=cfg.max_days_held,
            min_dte_to_hold=cfg.min_dte_to_hold,
        )
        out: list[dict[str, Any]] = []
        for pos in positions:
            try:
                quote = self.manager.broker.get_quote(pos.contract)
            except Exception:  # noqa: BLE001 - no quote means UNOBSERVABLE below
                quote = None
            decision = evaluate_exit(
                pos, quote, entry_time=self.manager.entry_time(pos.contract), now=now, policy=policy
            )
            item: dict[str, Any] = {
                "contract": pos.contract.occ_symbol.strip(),
                "quantity": pos.quantity,
                "action": decision.action,
                "reason": decision.reason,
                "pnl_pct": decision.pnl_pct,
                "trigger": decision.trigger,
            }
            if decision.action == EXIT:
                if not cfg.auto_exits:
                    item["result"] = "SHADOW_ONLY_AUTO_EXITS_OFF"
                elif not trading_allowed:
                    item["result"] = "DEFERRED_MARKET_CLOSED"
                else:
                    item.update(self._submit_exit(cfg, pos, quote, now))
            if decision.action != "HOLD":  # holds are the quiet default and would drown the journal
                self._journal(
                    "EXIT", pos.contract.underlying, item.get("result") or decision.action, pos.contract,
                    quote.bid if quote is not None else None,
                    {"action": decision.action, "reason": decision.reason, "trigger": decision.trigger,
                     "pnl_pct": decision.pnl_pct, "quantity": pos.quantity,
                     "risk_failures": item.get("risk_failures", [])},
                    order_id=item.get("order_id"),
                )
            out.append(item)
        return out

    def _submit_exit(self, cfg: EngineConfig, pos: Position, quote: Any, now: datetime) -> dict[str, Any]:
        pending = self.manager._pending_close_qty(pos.contract)
        quantity = pos.quantity - pending
        if quantity <= 0:
            return {"result": "ALREADY_CLOSING"}
        bucket = int(now.timestamp() // cfg.order_ttl_s)
        intent = OrderIntent(
            idempotency_key=f"x-{pos.contract.occ_symbol.strip()}-{bucket}",
            candidate_id="exit",
            contract=pos.contract,
            quantity=quantity,
            limit_price=sell_limit_for(quote.bid),
            note="automatic exit",
            side=Side.SELL_TO_CLOSE,
        )
        try:
            order = self.manager.submit(intent)
        except ValueError as exc:
            return {"result": "KEY_CONFLICT", "detail": str(exc)[:100]}
        result: dict[str, Any] = {"result": order.state.value, "order_id": order.id}
        if order.risk_failures:
            result["risk_failures"] = order.risk_failures
        return result

    def _run_entries(
        self,
        cfg: EngineConfig,
        positions: list[Position],
        trading_allowed: bool,
        cache: dict[str, Optional[MarketSnapshot]],
        report: dict[str, Any],
        now: datetime,
    ) -> None:
        def stop(note: str) -> None:
            report["entries_note"] = note

        if not cfg.auto_entries:
            return stop("Automatic entries are off")
        if not cfg.auto_exits:
            return stop("Entries require automatic exits")
        if not trading_allowed:
            return stop("Market closed: no new entries")
        if self.manager.kill_switch_active():
            return stop("Kill switch active: no new entries")
        if any(item["action"] == UNOBSERVABLE for item in report["exits"]):
            return stop("A held position cannot be priced: entries paused")
        if any(o.state is OrderState.ERROR_RECONCILE_REQUIRED for o in self.manager.list(open_only=True)):
            return stop("Unresolved orders need reconciliation: entries paused")

        held = {p.contract for p in positions}
        submitted = 0
        for symbol in cfg.watchlist:
            if submitted >= cfg.max_new_per_cycle:
                break
            snap = self._snapshot(symbol, cache, report)
            if snap is None:
                report["entries"].append({"symbol": symbol, "result": "NO_DATA"})
                continue
            cooldown = timedelta(seconds=cfg.reentry_cooldown_s)

            def cooling(contract: Any) -> bool:
                closed_at = self.manager.last_close_time(contract)
                return closed_at is not None and now - closed_at < cooldown

            raw = self.strategy.propose(snap, now)
            for p in raw[: self.JOURNAL_MAX_CANDIDATES]:
                if p.contract in held:
                    self._journal("ENTRY", symbol, "SKIPPED_HELD", p.contract, p.limit_price,
                                  {"rationale": p.rationale, "score": p.score}, snap)
                elif cooling(p.contract):
                    self._journal("ENTRY", symbol, "SKIPPED_COOLDOWN", p.contract, p.limit_price,
                                  {"rationale": p.rationale, "score": p.score}, snap)
            proposals = [p for p in raw if p.contract not in held and not cooling(p.contract)]
            if not proposals:
                report["entries"].append({"symbol": symbol, "result": "NO_PROPOSAL"})
                continue
            account = self.manager.broker.get_account()
            votes = self._committee_votes(cfg, symbol, snap, proposals, positions, account, now)
            chosen = None
            declined = False
            for proposal in proposals:  # best first; take the first one that fits the size cap
                quantity = size_quantity(account, self.manager.policy, proposal.limit_price)
                if quantity < 1:
                    continue
                if cfg.committee_mode == "active":  # the committee may refuse, or take less. Never more than the cap
                    d = votes.get(proposal.contract)
                    if d is None or d.disposition != cmt.ENTER:
                        declined = True
                        continue
                    quantity = min(quantity, d.quantity)
                chosen = (proposal, quantity)
                break
            if chosen is None and declined:
                report["entries"].append({"symbol": symbol, "result": "COMMITTEE_DECLINED"})
                for p in proposals[: self.JOURNAL_MAX_CANDIDATES]:
                    self._journal("ENTRY", symbol, "NOT_CHOSEN_COMMITTEE", p.contract, p.limit_price,
                                  {"rationale": p.rationale, "score": p.score,
                                   "why": "; ".join(votes[p.contract].reasons) if p.contract in votes else "not put to the committee: does not fit the size cap"}, snap)
                continue
            if chosen is None:
                for p in proposals[: self.JOURNAL_MAX_CANDIDATES]:
                    self._journal("ENTRY", symbol, "NOT_CHOSEN_SIZE_CAP", p.contract, p.limit_price,
                                  {"rationale": p.rationale, "score": p.score}, snap)
                report["entries"].append({"symbol": symbol, "result": "NOTHING_AFFORDABLE_WITHIN_SIZE_CAP"})
                continue
            proposal, quantity = chosen
            for p in proposals[: self.JOURNAL_MAX_CANDIDATES]:
                if p is not proposal:
                    self._journal("ENTRY", symbol, "NOT_CHOSEN", p.contract, p.limit_price,
                                  {"rationale": p.rationale, "score": p.score,
                                   "why": "ranked below the chosen candidate or over the size cap"}, snap)
            bucket = int(now.timestamp() // cfg.order_ttl_s)
            intent = OrderIntent(
                idempotency_key=f"e-{proposal.contract.occ_symbol.strip()}-{bucket}",
                candidate_id=f"{self.strategy.name}-{symbol}",
                contract=proposal.contract,
                quantity=quantity,
                limit_price=proposal.limit_price,
                note=json.dumps(proposal.rationale)[:200],
            )
            item: dict[str, Any] = {
                "symbol": symbol,
                "contract": proposal.contract.occ_symbol.strip(),
                "quantity": quantity,
                "limit_price": proposal.limit_price,
                "rationale": proposal.rationale,
            }
            if proposal.contract in votes:
                item["committee"] = {"decision": votes[proposal.contract].disposition, "mode": cfg.committee_mode,
                                     "reasons": list(votes[proposal.contract].reasons)}
            try:
                order = self.manager.submit(intent)
            except ValueError as exc:
                item.update(result="KEY_CONFLICT", detail=str(exc)[:100])
                report["entries"].append(item)
                self._journal("ENTRY", symbol, "KEY_CONFLICT", proposal.contract, proposal.limit_price,
                              {"rationale": proposal.rationale, "score": proposal.score, "quantity": quantity}, snap)
                continue
            item.update(result=order.state.value, order_id=order.id)
            if order.risk_failures:
                item["risk_failures"] = order.risk_failures
            report["entries"].append(item)
            self._journal("ENTRY", symbol, order.state.value, proposal.contract, proposal.limit_price,
                          {"rationale": proposal.rationale, "score": proposal.score, "quantity": quantity,
                           "risk_failures": order.risk_failures}, snap, order.id)
            if order.state in (OrderState.SUBMITTED, OrderState.PARTIALLY_FILLED, OrderState.FILLED):
                submitted += 1


class Runner:
    """Runs engine cycles on a background thread at the configured interval."""

    STALL_FACTOR = 3  # no successful cycle for this many intervals means the loop is stalled

    def __init__(self, engine: TradingEngine) -> None:
        self.engine = engine
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self.last_error: Optional[str] = None
        self.started_at: Optional[datetime] = None
        self.last_success_at: Optional[datetime] = None

    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive() and not self._stop.is_set()

    def start(self) -> None:
        with self._lock:
            if self.running():
                return
            self._stop.clear()
            self.started_at = self.engine.clock()
            self.last_success_at = None
            self._thread = threading.Thread(target=self._loop, name="optplat-runner", daemon=True)
            self._thread.start()

    def stop(self) -> None:
        with self._lock:
            self._stop.set()
            thread = self._thread
        if thread is not None:
            thread.join(timeout=5)

    def seconds_since_success(self) -> Optional[int]:
        """Seconds since the last cycle that finished without raising (or since start, if none has yet)."""
        ref = self.last_success_at or self.started_at
        if ref is None:
            return None
        return max(0, int((self.engine.clock() - ref).total_seconds()))

    def stalled(self) -> bool:
        since = self.seconds_since_success()
        return self.running() and since is not None and since > self.STALL_FACTOR * self.engine.config().interval_s

    def status(self) -> dict[str, Any]:
        return {
            "running": self.running(),
            "last_error": self.last_error,
            "last_success_at": self.last_success_at.isoformat() if self.last_success_at else None,
            "seconds_since_success": self.seconds_since_success(),
            "stalled": self.stalled(),
        }

    def health(self) -> dict[str, Any]:
        """The part safe for the unauthenticated health endpoint: no error text."""
        return {
            "running": self.running(),
            "stalled": self.stalled(),
            "seconds_since_success": self.seconds_since_success(),
        }

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.engine.run_cycle()
                self.last_error = None
                self.last_success_at = self.engine.clock()
            except Exception as exc:  # noqa: BLE001 - keep the loop alive; the error is surfaced in status
                self.last_error = f"{type(exc).__name__}: {str(exc)[:120]}"
            self._stop.wait(self.engine.config().interval_s)
