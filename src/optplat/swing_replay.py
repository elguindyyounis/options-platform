"""Replay the swing rule over past daily bars to see what it would have done, one day at a time.

    python -m optplat.swing_replay --data yahoo --months 12

This is a history check, not a live result and not evidence of an edge. The rule is the same code the live lane runs
(`SwingLane.step`), in a throwaway in-memory store with a fake clock, and on each day it can only see bars up to
that day. It covers funds only: historical earnings dates are not available, so single stocks would be contaminated by
earnings gaps and are left out. Entries are at the day's close, gaps and fills are not modelled, and the settings were
fixed before any result. The same bars were used to look at the outcome, so a good-looking replay still proves nothing.
"""
from __future__ import annotations

import argparse
import json
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional, Sequence

from . import swing
from .events import ETFS
from .marketdata import Bar, DemoDataProvider, MarketDataProvider, YahooDataProvider
from .store import Store


class _Feed(MarketDataProvider):
    """Serves history up to a cutoff day, so a step can never look ahead."""
    def __init__(self, bars: dict[str, list[Bar]], fictional: bool) -> None:
        self.bars, self.fictional, self.cutoff = bars, fictional, date.min
        self.name = "replay"

    def snapshot(self, symbol: str):  # pragma: no cover - not used
        raise NotImplementedError

    def quotes_for(self, contracts):  # pragma: no cover - not used
        return []

    def daily_bars(self, symbols: Sequence[str], months: int = 2) -> dict[str, list[Bar]]:
        return {s: [b for b in self.bars.get(s, []) if b.day <= self.cutoff] for s in symbols}


def replay(bars: dict[str, list[Bar]], fictional: bool, symbols: Optional[Sequence[str]] = None) -> dict[str, Any]:
    wanted = tuple(s for s in (symbols or swing.SYMBOLS) if s in ETFS)
    names = tuple(s for s in wanted if bars.get(s))
    days = sorted({b.day for s in names for b in bars[s]})
    store, feed = Store(":memory:"), _Feed(bars, fictional)
    box = [datetime(2000, 1, 1, tzinfo=timezone.utc)]
    lane = swing.SwingLane(feed, store, clock=lambda: box[0], calendar=None, symbols=names)
    for d in days[swing.MIN_BARS:]:
        feed.cutoff = d
        box[0] = datetime.combine(d + timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc)  # after that day's close
        lane.step(force=True)
    report = swing.build_report(store, fictional, box[0])
    closed = [t for t in report["trades"] if t["status"] == "CLOSED"]
    rets = [t["pnl_pct"] for t in closed if t["pnl_pct"] is not None]
    held = [(datetime.fromisoformat(t["closed_at"]) - datetime.fromisoformat(t["opened_at"])).days for t in closed]
    window = days[swing.MIN_BARS:] or days
    bh = []
    for s in names:
        inside = [b for b in bars[s] if window[0] <= b.day <= window[-1]]
        if len(inside) > 1 and inside[0].close > 0:
            bh.append((inside[-1].close / inside[0].close - 1) * 100)
    report["replay"] = {
        "from": window[0].isoformat() if window else None, "to": window[-1].isoformat() if window else None,
        "symbols": list(names), "days": len(window), "funds_asked": len(wanted),
        "bars_min": min((len(bars[s]) for s in names), default=0), "bars_max": max((len(bars[s]) for s in names), default=0),
        "mean_return_pct": round(sum(rets) / len(rets), 2) if rets else None,
        "worst_pct": min(rets) if rets else None, "best_pct": max(rets) if rets else None,
        "mean_days_held": round(sum(held) / len(held), 1) if held else None,
        "buy_and_hold_mean_pct": round(sum(bh) / len(bh), 2) if bh else None,
        "note": "Funds only, entries at the close, no gaps or earnings modelled. History is not evidence of an edge.",
    }
    return report


def render(rep: dict[str, Any]) -> str:
    r, s = rep["replay"], rep["summary"]
    lines = [f"Swing replay {r['from']} to {r['to']} on {len(r['symbols'])} of {r['funds_asked']} funds ({r['days']} days, {r['bars_min']} to {r['bars_max']} bars each)" + ("  (FICTIONAL demo data)" if rep["fictional"] else ""),
             f"  trades {s['total']}  open {s['open']}  closed {s['closed']}  winners {s['wins']}  win rate {s['win_rate_pct']}%",
             f"  realized {s['realized_pnl']:+.2f}  mean trade {r['mean_return_pct']}%  best {r['best_pct']}%  worst {r['worst_pct']}%  mean days held {r['mean_days_held']}",
             f"  for comparison, buying and holding the same funds over the same window: {r['buy_and_hold_mean_pct']}% on average",
             "  " + r["note"], ""]
    for t in sorted(rep["trades"], key=lambda x: x["why_entered"]["bar_day"]):
        end = f"{t['close_reason']:<11} {t['pnl']:+8.2f} ({t['pnl_pct']:+.2f}%)" if t["status"] == "CLOSED" else "open"
        lines.append(f"  {t['why_entered']['bar_day']}  {t['symbol']:<5} {t['quantity']:>4} @ {t['entry_price']:<9.2f} {end}")
    return "\n".join(lines)


def main(argv: Optional[Sequence[str]] = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--data", choices=["demo", "yahoo"], default="demo")
    ap.add_argument("--months", type=int, default=12)
    ap.add_argument("--json", help="also write the full report to this path (keep it outside the repo)")
    a = ap.parse_args(argv)
    provider: MarketDataProvider = DemoDataProvider() if a.data == "demo" else YahooDataProvider()
    names = tuple(s for s in swing.SYMBOLS if s in ETFS)
    rep = replay(provider.daily_bars(names, months=a.months), provider.fictional, names)  # type: ignore[attr-defined]
    print(render(rep))
    if a.json:
        with open(a.json, "w") as fh:
            json.dump(rep, fh, indent=2, default=str)


if __name__ == "__main__":
    main()
