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
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Optional

from . import committee as cmt
from .agents import Context
from .broker.sim import SimBroker
from .exits import EXIT, UNOBSERVABLE, ExitPolicy, evaluate_exit, exit_plan
from .market_clock import NY, session_status, upcoming_closures
from .events import EventCalendar
from .regime import spy_source
from .dataquality import MAX_FUTURE_SKEW_S, check_snapshot, frozen_issue, quote_fingerprint
from .diagnostics import clock_status
from .liquidity import size_vs_liquidity
from .flow import CAVEATS as FLOW_CAVEATS, related_themes, scan_flow
from .gex import ASSUMPTIONS as GEX_ASSUMPTIONS, net_gex
from .marketdata import MarketDataProvider, MarketSnapshot, snapshot_to_dict
from .models import Account, OrderIntent, OrderState, Position, Side, utcnow
from .orders import OrderManager
from .pricing import sell_limit_for
from .risk import RiskPolicy
from .scanner import Scanner
from .universe import SECTORS
from .shortterm import ShortTermLane
from .swing import SwingLane
from .optionlanes import OptionLanes
from .strategy import FlowFollowStrategy, LiquidTrendStrategy, Strategy

SYMBOL_RE = re.compile(r"^[A-Z][A-Z0-9.\-]{0,9}$")


def _age_hours(iso: Any, now: datetime) -> Optional[float]:
    """Hours since the contract last traded (display only); None when unknown or in the future."""
    try:
        then = datetime.fromisoformat(str(iso))
    except (TypeError, ValueError):
        return None
    if then.tzinfo is None:
        return None
    hours = (now - then).total_seconds() / 3600
    return round(hours, 1) if hours >= 0 else None


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
    scan_interval_s: int = 0  # 0 = off; otherwise the most-active and unusual-activity scan runs this often
    committee_mode: str = "shadow"  # off | shadow (records its votes only) | active (its vote and size apply)
    shortterm_enabled: bool = False  # research lane: simulated intraday share trades on the underlying, no orders
    swing_enabled: bool = False  # research lane: simulated multi-day share trades on daily bars, no orders
    option_lanes_enabled: bool = False  # research lanes: simulated long calls and puts from real chain quotes, no orders
    record_market_data: bool = True  # persist every snapshot/quote the engine sees (replay raw material)
    record_retention_days: int = 90  # 0 keeps recordings forever

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
            if isinstance(value, bool) != (name in ("auto_entries", "auto_exits", "enforce_market_hours", "record_snapshots", "record_market_data", "shortterm_enabled", "swing_enabled", "option_lanes_enabled")):
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
            (self.scan_interval_s == 0 or 600 <= self.scan_interval_s <= 86400, "scan_interval_s must be 0 or 600-86400"),
            (self.committee_mode in ("off", "shadow", "active"), "committee_mode must be off, shadow or active"),
            (0 <= self.record_retention_days <= 3650, "record_retention_days must be 0-3650"),
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


OUTCOME_WINDOW = 50  # cycles kept for the display-only outcome tally


class TradingEngine:
    def __init__(
        self,
        manager: OrderManager,
        provider: MarketDataProvider,
        strategy: Strategy,
        *,
        clock: Callable[[], datetime] = utcnow,
        default_config: Optional[EngineConfig] = None,
        calendar: Optional[EventCalendar] = None,
    ) -> None:
        self.calendar = calendar or EventCalendar(clock=clock)
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
        followed: dict[str, Strategy] = {strategy.name: strategy}  # the shadow book follows every strategy's top picks, not only the active one
        for extra in (LiquidTrendStrategy(), FlowFollowStrategy(mode="flagged"), FlowFollowStrategy(mode="nearer")):
            followed.setdefault(extra.name, extra)
        self.regime = spy_source(provider, clock)  # market-regime guard on new entries (owner decision 2026-11-24; tightening only)
        self.scanner = Scanner(provider, self.store, clock=clock, strategies=tuple(followed.values()), calendar=self.calendar)
        self.shortterm = ShortTermLane(provider, self.store, clock=clock)
        self.swing = SwingLane(provider, self.store, clock=clock, calendar=self.calendar)
        self.option_lanes = OptionLanes(provider, self.store, clock=clock, calendar=self.calendar)
        self._record_market = True  # per-cycle copy of cfg.record_market_data

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
            "market": {"open": is_open, "reason": reason, "hours_enforced": self._hours_enforced(self.config()),
                       "upcoming": upcoming_closures(self.clock())},
            "data_source": {"name": self.provider.name, "fictional": self.provider.fictional},
            "strategy": {"name": self.strategy.name, "version": self.strategy.version},
            "kill_switch": self.manager.kill_switch_active(),
            "last_cycle": self.last_cycle(),
            "clock": clock_status((self.last_cycle() or {}).get("clock_ahead_s"), MAX_FUTURE_SKEW_S),
            "sectors": list(SECTORS),
            "recorder": self.store.snapshot_stats(),
            "data_quality": {
                "window_hours": 24,
                "issues": self.store.data_issue_summary(self.clock() - timedelta(hours=24)),
            },
            "recent_outcomes": self.recent_outcomes(),
            "exit_plans": self.exit_plans(),
        }

    def exit_plans(self) -> list[dict[str, Any]]:
        """Display only: the sell levels the exit rules use for each open position."""
        cfg = self.config()
        policy = ExitPolicy(
            take_profit_pct=cfg.take_profit_pct,
            stop_loss_pct=cfg.stop_loss_pct,
            max_days_held=cfg.max_days_held,
            min_dte_to_hold=cfg.min_dte_to_hold,
        )
        try:
            now = self.clock()
            return [exit_plan(p, policy, now) for p in self.manager.broker.get_positions()]
        except Exception:  # noqa: BLE001 - a display helper must never break status
            return []

    def recent_outcomes(self) -> dict[str, Any]:
        """Display only: how many entry decisions of each kind over the last few cycles."""
        try:
            hist = json.loads(self.store.get_state("outcome_history", "") or "[]")
        except (ValueError, TypeError):
            hist = []
        if not isinstance(hist, list):
            hist = []
        totals: dict[str, int] = {}
        for cyc in hist:
            if isinstance(cyc, dict):
                for k, n in cyc.items():
                    if isinstance(n, int) and not isinstance(n, bool):
                        totals[str(k)] = totals.get(str(k), 0) + n
        return {"cycles": len(hist), "window": OUTCOME_WINDOW, "counts": totals}

    def _remember_outcomes(self, report: dict[str, Any]) -> None:
        counts: dict[str, int] = {}
        for item in report.get("entries") or []:
            key = str(item.get("result", "UNKNOWN")) if isinstance(item, dict) else "UNKNOWN"
            counts[key] = counts.get(key, 0) + 1
        try:
            hist = json.loads(self.store.get_state("outcome_history", "") or "[]")
            if not isinstance(hist, list):
                hist = []
        except (ValueError, TypeError):
            hist = []
        hist.append(counts)
        self.store.set_state("outcome_history", json.dumps(hist[-OUTCOME_WINDOW:]))

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
                "candidates": [],
                "gex": [],
                "gex_assumptions": list(GEX_ASSUMPTIONS),
                "flow": [],
                "flow_themes": [],
                "flow_caveats": list(FLOW_CAVEATS),
                "errors": [],
            }
            self._guard(report, "snapshot prune", lambda: self._maybe_prune_snapshots(cfg, now))
            self._maybe_learn(cfg, now)
            snapshots: dict[str, Optional[MarketSnapshot]] = {}
            self._record_market = cfg.record_market_data

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
        self._purge_recordings(report)
        report["finished_at"] = self.clock().isoformat()
        if report.get("trading_allowed"):  # equity only moves with the market; flat overnight points would stretch the chart
            try:
                acct = self.manager.broker.get_account()
                self.store.record_equity(self._cycle_now, acct.equity, acct.cash, acct.open_premium, self.provider.fictional)
            except Exception:  # noqa: BLE001 - a missing chart point must never affect a cycle
                pass
        self._guard(report, "outcome_history", lambda: self._remember_outcomes(report))
        self.store.set_state("last_cycle", json.dumps(report, default=str))
        self.store.audit("engine_cycle", None, {"exits": len(report["exits"]), "entries": len(report["entries"])})
        return report

    def _purge_recordings(self, report: dict[str, Any]) -> None:
        try:
            cfg = self.config()
            if cfg.record_market_data:
                self.store.purge_market_data(cfg.record_retention_days, now=self.clock())
        except Exception as exc:  # noqa: BLE001 - housekeeping must never stop the cycle
            report["errors"].append(f"recorder purge: {type(exc).__name__}: {str(exc)[:100]}")

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
                self._record_market_snapshot(cache[symbol], report)
                self._summarize_gex(cache[symbol], report)
                self._summarize_flow(cache[symbol], report)
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
        ahead = (snap.as_of - self._cycle_now).total_seconds()
        report["clock_ahead_s"] = max(ahead, report.get("clock_ahead_s", ahead))
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

    def _flow_view(self, symbol: str, now: datetime) -> Optional[dict[str, Any]]:
        """The scanner's unusual contracts on one name, from the newest stored scan. None when there is no scan."""
        try:
            scan = self.store.latest_scan(self.provider.fictional)
            if not scan:
                return None
            age_h = (now - datetime.fromisoformat(scan["as_of"])).total_seconds() / 3600
            rows = [{k: u.get(k) for k in ("contract", "right", "likely_side", "quoted_turnover_usd", "volume_oi_ratio")}
                    for u in scan.get("unusual", []) if u.get("symbol") == symbol]
            return {"as_of": scan["as_of"], "age_h": round(age_h, 1), "rows": rows}
        except Exception:  # noqa: BLE001 - flow is advisory; no view means the agent abstains
            return None

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
                view = self.calendar.view(symbol, now.astimezone(NY).date(), p.contract.expiry)
                ctx = Context(snap, p, now, account, self.manager.policy, tuple(positions), cap,
                              cfg.min_dte_to_hold, cfg.stop_loss_pct, view, self._flow_view(symbol, now))
                d = cmt.decide(ctx, weights, trust)
            except Exception:  # noqa: BLE001 - no decision: shadow ignores it, active mode refuses the candidate
                continue
            votes[p.contract] = d
            self._journal(cmt.KIND, symbol, d.disposition, p.contract, p.limit_price, d.to_payload(weights, trust), snap)
        return votes

    def maybe_shortterm(self) -> Optional[dict[str, Any]]:
        """One pass of the short-term research lane when it is switched on and the market is open (or the data is
        fictional with hours not enforced). It never places an order and never raises into the trading loop."""
        try:
            cfg = self.config()
            if not cfg.shortterm_enabled:
                return None
            if not session_status(self.clock())[0] and self._hours_enforced(cfg):
                return None
            return self.shortterm.step()
        except Exception:  # noqa: BLE001
            return None

    def maybe_swing(self, force: bool = False) -> Optional[dict[str, Any]]:
        """One pass of the swing research lane when it is switched on. Throttled inside the lane. It never places an
        order and never raises into the trading loop."""
        try:
            if not self.config().swing_enabled:
                return None
            return self.swing.step(force=force)
        except Exception:  # noqa: BLE001
            return None

    def maybe_option_lanes(self, force: bool = False) -> Optional[list[dict[str, Any]]]:
        """One pass of the five options research lanes when they are switched on and quotes exist (the market is open,
        or the data is fictional with hours not enforced). Each lane throttles itself. Nothing here places an order, and
        nothing raises into the trading loop."""
        try:
            cfg = self.config()
            if not cfg.option_lanes_enabled:
                return None
            if not session_status(self.clock())[0] and self._hours_enforced(cfg):
                return None
            return self.option_lanes.step(force=force)
        except Exception:  # noqa: BLE001
            return None

    def maybe_scan(self) -> None:
        """Start the background scan when it is due. Never blocks or raises into the trading loop."""
        try:
            cfg = self.config()
            if cfg.scan_interval_s == 0:
                return
            now = self.clock()
            last = self.store.get_state("scan_last_started", "")
            if last and (now - datetime.fromisoformat(last)).total_seconds() < cfg.scan_interval_s:
                return
            if self.scanner.start():
                self.store.set_state("scan_last_started", now.isoformat())
        except Exception:  # noqa: BLE001
            pass

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
    @staticmethod
    def _summarize_flow(snap: MarketSnapshot, report: dict[str, Any]) -> None:
        """Display-only unusual-turnover radar; a failure is reported but never affects trading."""
        try:
            report["flow"].extend(scan_flow(snap))
            report["flow"].sort(key=lambda r: ({"EXTREME": 0, "HIGH": 1, "ELEVATED": 2}[r["tier"]], -(r["premium_at_quoted_mid_usd"] or 0)))
            del report["flow"][30:]
            report["flow_themes"] = related_themes(report["flow"])
        except Exception as exc:  # noqa: BLE001
            report["errors"].append(f"flow {snap.symbol}: {type(exc).__name__}")

    @staticmethod
    def _summarize_gex(snap: MarketSnapshot, report: dict[str, Any]) -> None:
        """Display-only context; a failure here is reported but never affects trading."""
        try:
            report["gex"].append(net_gex(snap))
        except Exception as exc:  # noqa: BLE001
            report["errors"].append(f"gex {snap.symbol}: {type(exc).__name__}")

    def _record_market_snapshot(self, snap: MarketSnapshot, report: dict[str, Any]) -> None:
        """Recording is best effort: a storage failure is reported but never blocks trading or exits."""
        if not self._record_market:
            return
        try:
            self.store.record_market_snapshot(snap, recorded_at=self.clock())
        except Exception as exc:  # noqa: BLE001
            report["errors"].append(f"recorder {snap.symbol}: {type(exc).__name__}: {str(exc)[:100]}")

    def _record_market_quotes(self, quotes: list, report: dict[str, Any]) -> None:
        if not self._record_market:
            return
        try:
            self.store.record_market_quotes(quotes, fictional=self.provider.fictional, recorded_at=self.clock())
        except Exception as exc:  # noqa: BLE001
            report["errors"].append(f"recorder quotes: {type(exc).__name__}: {str(exc)[:100]}")

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
                held = self.provider.quotes_for(missing)
                self._record_market_quotes(held, report)
                for quote in held:
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
            blocked_why = ""
            kept = []
            n_blocked = 0
            for p in proposals:
                ok, why, reg = self.regime.allows(p.contract.right.value)
                if ok:
                    kept.append(p)
                else:
                    blocked_why = why
                    n_blocked += 1
                    if n_blocked <= self.JOURNAL_MAX_CANDIDATES:
                        self._journal("ENTRY", symbol, "SKIPPED_REGIME", p.contract, p.limit_price,
                                      {"rationale": p.rationale, "score": p.score, "why": why, "regime": reg.to_dict() if reg else None}, snap)
            proposals = kept
            if blocked_why and not proposals:
                report["entries"].append({"symbol": symbol, "result": "BLOCKED_REGIME", "reason": blocked_why[:300]})
                continue
            if not proposals:
                item_np: dict[str, Any] = {"symbol": symbol, "result": "NO_PROPOSAL"}
                explain = getattr(self.strategy, "explain_no_proposal", None)
                if callable(explain):
                    try:
                        item_np["reason"] = str(explain(snap, now))[:300]
                    except Exception:  # noqa: BLE001  # display only: never let it affect trading
                        pass
                report["entries"].append(item_np)
                continue
            for cand in proposals[:3]:  # display only: runner-ups the owner can see, not orders
                report["candidates"].append(
                    {
                        "symbol": symbol,
                        "contract": cand.contract.occ_symbol.strip(),
                        "score": cand.score,
                        "limit_price": cand.limit_price,
                        "trend": cand.rationale.get("trend"),
                        "spread_pct": cand.rationale.get("spread_pct"),
                        "dte": cand.rationale.get("dte"),
                        "volume": cand.rationale.get("volume"),
                        "open_interest": cand.rationale.get("open_interest"),
                        "last_trade_age_hours": _age_hours(cand.rationale.get("last_trade_at"), now),
                    }
                )
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
            try:  # display only: never let it affect trading
                item["size_vs_liquidity"] = size_vs_liquidity(
                    quantity, proposal.rationale.get("volume"), proposal.rationale.get("open_interest")
                )
            except Exception:  # noqa: BLE001
                pass
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
        report["candidates"].sort(key=lambda c: (-c["score"], c["contract"]))
        del report["candidates"][10:]


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
        self.last_failure_at: Optional[datetime] = None
        self.consecutive_failures = 0

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

    def seconds_since_success(self, now: Optional[datetime] = None) -> Optional[int]:
        """Seconds since the last cycle that finished without raising (or since start, if none has yet)."""
        ref = self.last_success_at or self.started_at
        if ref is None:
            return None
        return max(0, int(((now or self.engine.clock()) - ref).total_seconds()))

    def stalled(self, now: Optional[datetime] = None) -> bool:
        since = self.seconds_since_success(now)
        return self.running() and since is not None and since > self.STALL_FACTOR * self.engine.config().interval_s

    def status(self, now: Optional[datetime] = None) -> dict[str, Any]:
        return {
            "running": self.running(),
            "last_error": self.last_error,
            "last_success_at": self.last_success_at.isoformat() if self.last_success_at else None,
            "seconds_since_success": self.seconds_since_success(now),
            "stalled": self.stalled(now),
            "last_failure_at": self.last_failure_at.isoformat() if self.last_failure_at else None,
            "consecutive_failures": self.consecutive_failures,
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
                self.consecutive_failures = 0
                self.last_success_at = self.engine.clock()
                self.engine.maybe_scan()
                self.engine.maybe_shortterm()
                self.engine.maybe_swing()
                self.engine.maybe_option_lanes()
            except Exception as exc:  # noqa: BLE001 - keep the loop alive; the error is surfaced in status
                self.consecutive_failures += 1
                self.last_failure_at = self.engine.clock()
                self.last_error = f"{type(exc).__name__}: {str(exc)[:120]}"
            self._stop.wait(self.engine.config().interval_s)
