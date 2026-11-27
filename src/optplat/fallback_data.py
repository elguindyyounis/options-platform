"""IBKR first; Yahoo only for research data IBKR did not give (owner decision, 2026-11-27).

The owner said IBKR is preferred and Yahoo should be used only when there is really no market data from IBKR. So:

* Chains (``snapshot`` / ``snapshot_window``), daily bars and intraday bars come from IBKR. Only when IBKR fails or
  returns nothing for a symbol does that symbol's data come from Yahoo. A fallback chain is labelled
  ``FALLBACK_SOURCE``, so every recorded snapshot and scan says where it came from, and the option lanes refuse to
  open simulated trades on it (their marks are paused under ``execution_veto``, so an entry would have no exit).
* Anything that can lead to an order never falls back: ``quotes_for``, ``decision_quotes_for`` and ``execution_quote``
  are IBKR's alone, and ``execution_veto`` stays on. A Yahoo quote has no verified time, so the risk policy would
  refuse it anyway; this keeps it from ever being offered.
"""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from typing import Any, Callable, Optional, Sequence

from .marketdata import MarketDataProvider, MarketSnapshot
from .models import OptionContract, Quote


FALLBACK_SOURCE = "yahoo-fallback"


class IBKRWithYahooFallback(MarketDataProvider):
    execution_veto = True

    def __init__(self, primary: MarketDataProvider, fallback_factory: Callable[[], MarketDataProvider],
                 clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc)) -> None:
        self.primary = primary
        self._factory = fallback_factory
        self._fallback: Optional[MarketDataProvider] = None
        self._fallback_error: Optional[str] = None
        self._clock = clock
        self.name = f"{primary.name}+yahoo-fallback"
        self.fallback_counts: dict[str, int] = {"snapshot": 0, "daily_bars": 0, "intraday_bars": 0}
        self.last_fallback: Optional[dict[str, Any]] = None
        self.last_chain_why: dict[str, str] = {}  # per symbol: why the newest chain did not come from IBKR

    # ---- the order path: IBKR only, never Yahoo
    def quotes_for(self, contracts: Sequence[OptionContract]) -> list[Quote]:
        return self.primary.quotes_for(contracts)

    def __getattr__(self, attr: str) -> Any:
        # execution_quote, decision_quotes_for and anything else IBKR-specific pass straight to IBKR.
        if attr in ("primary", "_factory", "_fallback"):
            raise AttributeError(attr)
        return getattr(self.primary, attr)

    # ---- research data: IBKR, else Yahoo
    def _yahoo(self) -> Optional[MarketDataProvider]:
        if self._fallback is None and self._fallback_error is None:
            try:
                self._fallback = self._factory()
            except Exception as exc:  # noqa: BLE001 - no Yahoo means no fallback, never a crash
                self._fallback_error = type(exc).__name__
        return self._fallback

    def _note(self, kind: str, symbol: str, why: str) -> None:
        self.fallback_counts[kind] += 1
        self.last_fallback = {"kind": kind, "symbol": symbol, "why": why, "at": self._clock().isoformat()}

    def _chain(self, symbol: str, call: Callable[[MarketDataProvider], MarketSnapshot]) -> MarketSnapshot:
        try:
            snap = call(self.primary)
            if snap.rows:
                self.last_chain_why.pop(symbol, None)
                return snap
            why: str = "IBKR returned no usable quotes"
        except Exception as exc:  # noqa: BLE001
            snap, why = None, f"IBKR failed: {type(exc).__name__}: {str(exc)[:80]}"
        self.last_chain_why[symbol] = why
        yahoo = self._yahoo()
        if yahoo is None:
            if snap is not None:
                return snap
            raise RuntimeError(f"{why}; Yahoo fallback unavailable")
        out = replace(call(yahoo), source=FALLBACK_SOURCE, timestamp_verified=False)
        self._note("snapshot", symbol, why)
        return out

    def snapshot(self, symbol: str) -> MarketSnapshot:
        return self._chain(symbol, lambda p: p.snapshot(symbol))

    def snapshot_window(self, symbol: str, min_dte: int, max_dte: int, max_expiries: int = 4) -> MarketSnapshot:
        return self._chain(symbol, lambda p: p.snapshot_window(symbol, min_dte, max_dte, max_expiries))

    def daily_bars(self, symbols: Sequence[str], months: int = 2) -> dict[str, list[Any]]:
        try:
            out = dict(self.primary.daily_bars(symbols, months))
        except Exception:  # noqa: BLE001
            out = {}
        missing = [s for s in symbols if not out.get(s)]
        yahoo = self._yahoo() if missing else None
        if yahoo is not None:
            try:
                got = yahoo.daily_bars(missing, months)
            except Exception:  # noqa: BLE001 - those names stay unknown this round
                got = {}
            for s in missing:
                if got.get(s):
                    out[s] = got[s]
                    self._note("daily_bars", s, "IBKR had no bars")
        return out

    def intraday_bars(self, symbol: str) -> list[Any]:
        try:
            bars = self.primary.intraday_bars(symbol)
            if bars:
                return bars
            why = "IBKR returned no bars"
        except Exception as exc:  # noqa: BLE001
            why = f"IBKR failed: {type(exc).__name__}: {str(exc)[:80]}"
        yahoo = self._yahoo()
        if yahoo is None:
            return []
        bars = yahoo.intraday_bars(symbol)
        self._note("intraday_bars", symbol, why)
        return bars

    def health(self) -> dict[str, Any]:
        h = self.primary.health()
        h = dict(h) if isinstance(h, dict) else {"primary": h}
        h["yahoo_fallback"] = {"available": self._fallback_error is None, "error": self._fallback_error,
                               "counts": dict(self.fallback_counts), "last": self.last_fallback}
        usage = getattr(self.primary, "usage", None)
        if callable(usage):
            try:
                h["platform_usage"] = usage()
            except Exception:  # noqa: BLE001 - display only
                pass
        return h
