"""The paper options account's size and its fresh starts (owner decision 2026-11-27).

The owner plans to trade live with about $1,000 one day, and a $100,000 paper account says nothing about that: its 1%
per-order cap is $1,000, while at $1,000 one SPY contract is a third of the account. So the paper account can be given
the size the owner names, with sizing limits that let it buy a contract at that size.

Changing the size starts a new account (an "epoch"). The simulator rebuilds its cash by replaying saved fills, so the
old fills cannot be replayed onto a new, smaller balance. From the epoch on, the account, its reports and its equity
curve count only orders and points recorded since the epoch; everything earlier stays in the database and the export.
Open positions from the old account are not carried over (they are counted and reported, never guessed into the new
cash). Nothing here places, sizes or cancels an order; it is read once at startup.

Settings in config.env, all optional (unset means today's defaults, nothing changes):
  OPTPLAT_PAPER_START_CASH        starting balance of the paper options account, $100 to $10,000,000 (default 100000)
  OPTPLAT_MAX_POSITION_PCT        worst-case premium per new order, % of equity, 0.1 to 50 (default: RiskPolicy's 1.0)
  OPTPLAT_MAX_TOTAL_PREMIUM_PCT   open premium plus the new order, % of equity, 1 to 100 (default: RiskPolicy's 10.0)
Raising the two percentages is the owner's decision (CLAUDE.md); the code defaults are not changed.
"""
from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime
from typing import Any, Mapping, Optional

from .risk import RiskPolicy

DEFAULT_START_CASH = 100_000.0
STATE_KEY = "account_epoch"


def _number(env: Mapping[str, str], key: str, lo: float, hi: float) -> Optional[float]:
    raw = env.get(key, "").strip()
    if not raw:
        return None
    try:
        v = float(raw)
    except ValueError:
        raise ValueError(f"{key} must be a number, got {raw!r}") from None
    if not (lo <= v <= hi):
        raise ValueError(f"{key} must be between {lo:g} and {hi:g}, got {v:g}")
    return v


def start_cash(env: Mapping[str, str]) -> float:
    v = _number(env, "OPTPLAT_PAPER_START_CASH", 100, 10_000_000)
    return DEFAULT_START_CASH if v is None else v


def risk_policy(env: Mapping[str, str], *, require_verified_quote_time: bool) -> RiskPolicy:
    """RiskPolicy with the owner's per-order and total-premium percentages, if set. Every other limit is the default."""
    base = RiskPolicy(require_verified_quote_time=require_verified_quote_time)
    per = _number(env, "OPTPLAT_MAX_POSITION_PCT", 0.1, 50)
    total = _number(env, "OPTPLAT_MAX_TOTAL_PREMIUM_PCT", 1, 100)
    kw: dict[str, Any] = {}
    if per is not None:
        kw["max_position_pct"] = per
    if total is not None:
        kw["max_total_premium_pct"] = total
    if kw.get("max_position_pct", base.max_position_pct) > kw.get("max_total_premium_pct", base.max_total_premium_pct):
        raise ValueError("OPTPLAT_MAX_POSITION_PCT cannot be larger than OPTPLAT_MAX_TOTAL_PREMIUM_PCT")
    if not kw:
        return base
    return replace(base, version=base.version + "-owner", **kw)


def resolve_epoch(stored: str, cash: float, now: datetime) -> tuple[Optional[dict[str, Any]], bool]:
    """(epoch, started_now). No epoch while the account was never resized; a new one whenever the size changes."""
    try:
        epoch = json.loads(stored) if stored else None
    except ValueError:
        epoch = None
    if epoch is not None and not (isinstance(epoch, dict) and isinstance(epoch.get("start_cash"), (int, float))
                                  and isinstance(epoch.get("started_at"), str)):
        epoch = None
    if epoch is None and cash == DEFAULT_START_CASH:
        return None, False
    if epoch is not None and float(epoch["start_cash"]) == cash:
        return epoch, False
    return {"start_cash": cash, "started_at": now.isoformat()}, True


def start_account(store: Any, cash: float, now: datetime) -> Optional[dict[str, Any]]:
    """Apply the account size at startup: keep the current epoch, start a new one, or do nothing (never resized).
    Sets ``store.account_since`` so the account, reports and curve count only what happened since the start."""
    from .broker.sim import SimBroker

    epoch, started = resolve_epoch(store.get_state(STATE_KEY), cash, now)
    if epoch is None:
        return None
    left = 0
    if started:
        left = SimBroker().restore(store.list_orders(limit=1_000_000, all_history=True))["open_positions"]
        store.set_state(STATE_KEY, json.dumps(epoch))
        store.audit("account_epoch_started", None, {**epoch, "open_positions_left_in_old_account": left})
    store.account_since = epoch["started_at"]
    return {**epoch, "started_now": started, "open_positions_left": left}
