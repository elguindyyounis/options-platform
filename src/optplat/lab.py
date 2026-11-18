"""Strategy lab: run fixed, pre-declared entry rules over many symbols and windows, again and again, and say how often they win.

    python -m optplat.lab --data yahoo --months 24

Research only. Nothing here places an order or feeds a lane. Each strategy is a plain rule on daily closes with fixed exits
(stop, target, maximum hold), declared in ``STRATEGIES`` BEFORE any result. For every strategy the lab reports the win rate
with a Wilson 95% interval, the mean trade after slippage, the same numbers on the LATER 30% of dates (not used to pick
anything), the result with the three best trades removed, how many of four consecutive windows were positive, and which
market regime (SPY above or below its 50 day average) it fired in. It then asks the question that matters: does the rule beat
picking the same number of entries at random, with the same exits? That is repeated ``REPEATS`` times and gives a p-value.

Honest limits: daily closes only (stops and targets are checked on closes, no intraday path, no gaps inside a day); the
underlying is traded, not options (an option's win rate would be different, usually lower after spread); all strategies share
the same history, so trying several makes a lucky one likely (the bar is Bonferroni-corrected); a result on fictional demo data
means nothing and is labelled so. A pass here is "not refuted yet", never "has an edge".
"""
from __future__ import annotations

import argparse
import json
import math
import random
from dataclasses import dataclass
from datetime import date
from typing import Any, Callable, Optional, Sequence

from .marketdata import Bar, DemoDataProvider, MarketDataProvider, YahooDataProvider

SLIPPAGE_PCT = 0.05          # each way, against the trade (same as the swing lane)
REPEATS = 300                # random-baseline repeats per strategy
MIN_BARS = 60
MIN_INDEPENDENT_DAYS = 30    # distinct entry days; trades on one day are correlated
MIN_LATER_TRADES = 15
ALPHA = 0.05
LATER_FRACTION = 0.30
WINDOWS = 4
REGIME_SYMBOL = "SPY"


# ------------------------------------------------------------------ indicators on a list of closes
def sma(c: Sequence[float], n: int) -> Optional[float]:
    return sum(c[-n:]) / n if len(c) >= n else None


def rsi(c: Sequence[float], n: int) -> Optional[float]:
    if len(c) < n + 1:
        return None
    gains = losses = 0.0
    for a, b in zip(c[-n - 1:-1], c[-n:]):
        d = b - a
        gains, losses = (gains + d, losses) if d > 0 else (gains, losses - d)
    if gains + losses == 0:
        return 50.0
    return 100.0 if losses == 0 else 100 - 100 / (1 + gains / losses)


# ------------------------------------------------------------------ the strategies (declared before any result)
def pullback(c: Sequence[float]) -> bool:
    """An uptrend that dipped and is turning up: SMA20 above SMA50, RSI(14) at or below 45 on one of the last 3 bars, today up."""
    if len(c) < 55:
        return False
    f, s = sma(c, 20), sma(c, 50)
    dipped = any((r := rsi(c[:len(c) - k], 14)) is not None and r <= 45 for k in (1, 2, 3))
    return bool(f and s and f > s and dipped and c[-1] > c[-2] and abs(c[-1] / c[-2] - 1) < 0.05)


def breakout(c: Sequence[float]) -> bool:
    """Close above the prior 20 day high, in an uptrend (above SMA50)."""
    return len(c) >= 55 and c[-1] > max(c[-21:-1]) and c[-1] > (sma(c, 50) or float("inf"))


def reversion(c: Sequence[float]) -> bool:
    """A sharp two day drop (RSI(2) under 10) inside an uptrend (above SMA50)."""
    r = rsi(c, 2)
    return len(c) >= 55 and r is not None and r < 10 and c[-1] > (sma(c, 50) or float("inf"))


def momentum(c: Sequence[float]) -> bool:
    """Up more than 8% over 40 bars with the close above both SMA20 and SMA50."""
    return len(c) >= 55 and c[-1] / c[-41] - 1 > 0.08 and c[-1] > (sma(c, 20) or 1e18) and c[-1] > (sma(c, 50) or 1e18)


@dataclass(frozen=True)
class Strategy:
    name: str
    description: str
    entry: Callable[[Sequence[float]], bool]
    stop_pct: float = 5.0
    target_pct: float = 7.5
    max_hold: int = 10


STRATEGIES: tuple[Strategy, ...] = (
    Strategy("pullback-trend", "Buy a dip that is turning up inside an uptrend", pullback),
    Strategy("breakout-20d", "Buy a close above the 20 day high in an uptrend", breakout),
    Strategy("rsi2-reversion", "Buy a sharp two day drop inside an uptrend", reversion, 5.0, 4.0, 5),
    Strategy("momentum-40d", "Buy strength: up over 8% in 40 bars, above both averages", momentum, 6.0, 9.0, 15),
)


# ------------------------------------------------------------------ one trade
def outcome(closes: Sequence[float], i: int, st: Strategy) -> Optional[tuple[float, int, str]]:
    """Enter at the close of bar i, exit on the first later close at the stop or target, else after max_hold bars.
    Returns (return %, bars held, reason) after slippage each way, or None if the history ends before an exit."""
    entry = closes[i] * (1 + SLIPPAGE_PCT / 100)
    for k in range(1, st.max_hold + 1):
        if i + k >= len(closes):
            return None
        px = closes[i + k]
        reason = "stop" if px <= entry * (1 - st.stop_pct / 100) else "target" if px >= entry * (1 + st.target_pct / 100) else "time" if k == st.max_hold else ""
        if reason:
            return round((px * (1 - SLIPPAGE_PCT / 100) / entry - 1) * 100, 3), k, reason
    return None


def trades_for(bars: dict[str, list[Bar]], st: Strategy, regime: dict[date, str]) -> list[dict[str, Any]]:
    out = []
    for sym, bs in bars.items():
        closes = [b.close for b in bs]
        i = MIN_BARS - 1
        while i < len(closes) - 1:
            if st.entry(closes[:i + 1]):
                res = outcome(closes, i, st)
                if res is None:
                    break
                out.append({"symbol": sym, "day": bs[i].day, "ret_pct": res[0], "held": res[1], "reason": res[2],
                            "regime": regime.get(bs[i].day, "UNKNOWN")})
                i += res[1]  # one position per symbol at a time
            i += 1
    out.sort(key=lambda t: (t["day"], t["symbol"]))
    return out


def regime_map(bars: dict[str, list[Bar]]) -> dict[date, str]:
    bs = bars.get(REGIME_SYMBOL) or []
    closes = [b.close for b in bs]
    return {b.day: ("UP" if closes[i] > (sma(closes[:i + 1], 50) or float("inf")) else "DOWN")
            for i, b in enumerate(bs) if i >= 49}


# ------------------------------------------------------------------ statistics
def wilson(wins: int, n: int, z: float = 1.96) -> Optional[list[float]]:
    if n <= 0:
        return None
    p = wins / n
    d = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / d
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return [round(max(0.0, centre - half) * 100, 1), round(min(1.0, centre + half) * 100, 1)]


def summarize(trades: Sequence[dict[str, Any]]) -> dict[str, Any]:
    n = len(trades)
    rets = sorted(t["ret_pct"] for t in trades)
    wins = sum(1 for t in trades if t["ret_pct"] > 0)
    trim = rets[:-3] if n > 3 else []
    return {"trades": n, "independent_days": len({t["day"] for t in trades}), "wins": wins,
            "win_rate_pct": round(wins / n * 100, 1) if n else None, "win_rate_ci95": wilson(wins, n),
            "mean_pct": round(sum(rets) / n, 3) if n else None, "median_pct": round(rets[n // 2], 3) if n else None,
            "mean_without_top3_pct": round(sum(trim) / len(trim), 3) if trim else None,
            "worst_pct": rets[0] if n else None, "best_pct": rets[-1] if n else None}


def random_baseline(bars: dict[str, list[Bar]], st: Strategy, mine: Sequence[dict[str, Any]], seed: int) -> dict[str, Any]:
    """Pick as many entries per symbol as the rule did, at random flat days, with the same exits. Repeated REPEATS times."""
    need: dict[str, int] = {}
    for t in mine:
        need[t["symbol"]] = need.get(t["symbol"], 0) + 1
    table = {}
    for sym, k in need.items():
        closes = [b.close for b in bars[sym]]
        table[sym] = (k, [(i, o[0]) for i in range(MIN_BARS - 1, len(closes) - 1) if (o := outcome(closes, i, st)) is not None])
    if not table or not mine:
        return {"repeats": 0, "mean_pct": None, "p_value": None}
    rng, means = random.Random(seed), []
    for _ in range(REPEATS):
        rets: list[float] = []
        for sym, (k, pool) in table.items():
            if pool:
                rets += [r for _, r in rng.sample(pool, min(k, len(pool)))]
        means.append(sum(rets) / len(rets) if rets else 0.0)
    mine_mean = sum(t["ret_pct"] for t in mine) / len(mine)
    p = (1 + sum(1 for m in means if m >= mine_mean)) / (REPEATS + 1)
    return {"repeats": REPEATS, "mean_pct": round(sum(means) / len(means), 3), "p_value": round(p, 4)}


def evaluate(bars: dict[str, list[Bar]], fictional: bool, strategies: Sequence[Strategy] = STRATEGIES) -> dict[str, Any]:
    bars = {s: b for s, b in bars.items() if len(b) >= MIN_BARS + 12}
    days = sorted({b.day for bs in bars.values() for b in bs})
    regime = regime_map(bars)
    split = days[int(len(days) * (1 - LATER_FRACTION))] if days else None
    edges = [days[int(len(days) * k / WINDOWS)] for k in range(WINDOWS)] + [date.max] if days else []
    alpha = ALPHA / max(len(strategies), 1)
    results = []
    for n, st in enumerate(strategies):
        tr = trades_for(bars, st, regime)
        later = [t for t in tr if split and t["day"] >= split]
        wins_ = [summarize([t for t in tr if edges[k] <= t["day"] < edges[k + 1]]) for k in range(WINDOWS)] if edges else []
        allr, laterr = summarize(tr), summarize(later)
        base = random_baseline(bars, st, tr, seed=1000 + n)
        by_regime = {}
        for g in ("UP", "DOWN", "UNKNOWN"):
            sub = [t for t in tr if t["regime"] == g]
            if sub:
                by_regime[g] = {**summarize(sub), "enough": len(sub) >= 30}
        why = []
        if allr["independent_days"] < MIN_INDEPENDENT_DAYS:
            why.append(f"only {allr['independent_days']} independent entry days (need {MIN_INDEPENDENT_DAYS})")
        if laterr["trades"] < MIN_LATER_TRADES:
            why.append(f"only {laterr['trades']} trades in the later {int(LATER_FRACTION * 100)}% of dates (need {MIN_LATER_TRADES})")
        elif (laterr["mean_pct"] or 0) <= 0:
            why.append("mean trade is not positive on the later dates")
        if (allr["mean_without_top3_pct"] or 0) <= 0:
            why.append("not positive once the three best trades are removed")
        if base["p_value"] is None or base["p_value"] > alpha:
            why.append(f"does not beat random entries with the same exits (p {base['p_value']}, bar {alpha:.4f})")
        results.append({"name": st.name, "description": st.description,
                        "exits": {"stop_pct": st.stop_pct, "target_pct": st.target_pct, "max_hold_bars": st.max_hold},
                        "all": allr, "later": laterr, "windows_positive": sum(1 for w in wins_ if (w["mean_pct"] or 0) > 0),
                        "windows_with_trades": sum(1 for w in wins_ if w["trades"]), "random": base, "by_regime": by_regime,
                        "verdict": "NOT_REFUTED_YET" if not why else "NOT_PROVEN", "reasons": why})
    return {"fictional": fictional, "symbols": sorted(bars), "bars_max": max((len(b) for b in bars.values()), default=0),
            "from": days[0].isoformat() if days else None, "to": days[-1].isoformat() if days else None,
            "later_from": split.isoformat() if split else None, "strategies_tried": len(strategies), "alpha_per_strategy": round(alpha, 4),
            "results": results,
            "note": ("FICTIONAL demo data: these numbers mean nothing. " if fictional else "") +
                    "Underlying on daily closes, not options; stops are checked on closes only. NOT_REFUTED_YET is not an edge: "
                    "the history was also used to look at the result, and every extra strategy tried makes a lucky one likelier."}


def render(rep: dict[str, Any]) -> str:
    lines = [f"Strategy lab {rep['from']} to {rep['to']}, {len(rep['symbols'])} symbols" + ("  (FICTIONAL demo data)" if rep["fictional"] else ""), "  " + rep["note"], ""]
    for r in rep["results"]:
        a, lt = r["all"], r["later"]
        lines += [f"{r['name']}: {r['verdict']}  ({r['description']})",
                  f"  all dates: {a['trades']} trades on {a['independent_days']} days, win rate {a['win_rate_pct']}% (95% {a['win_rate_ci95']}), mean {a['mean_pct']}%, without top 3 {a['mean_without_top3_pct']}%",
                  f"  later dates: {lt['trades']} trades, win rate {lt['win_rate_pct']}%, mean {lt['mean_pct']}%   windows positive: {r['windows_positive']} of {r['windows_with_trades']}",
                  f"  random entries, same exits: mean {r['random']['mean_pct']}%, p {r['random']['p_value']}"]
        for g, x in r["by_regime"].items():
            lines.append(f"  market {g}: {x['trades']} trades, win rate {x['win_rate_pct']}%, mean {x['mean_pct']}%" + ("" if x["enough"] else "  (too few to judge)"))
        lines += [f"  why not proven: {w}" for w in r["reasons"]] + [""]
    return "\n".join(lines)


def run_and_store(provider: MarketDataProvider, store: Any, symbols: Sequence[str], months: int = 24) -> dict[str, Any]:
    rep = evaluate(provider.daily_bars(symbols, months=months), provider.fictional)  # type: ignore[attr-defined]
    store.set_state("lab_latest", json.dumps(rep, default=str))
    return rep


def main(argv: Optional[Sequence[str]] = None) -> None:
    from .context import CORE
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--data", choices=["demo", "yahoo"], default="demo")
    ap.add_argument("--months", type=int, default=24)
    ap.add_argument("--symbols", nargs="*", default=None)
    ap.add_argument("--json", help="also write the full report to this path (keep it outside the repo)")
    ap.add_argument("--save-db", help="also store the report in this platform database so the dashboard shows it")
    a = ap.parse_args(argv)
    provider: MarketDataProvider = DemoDataProvider() if a.data == "demo" else YahooDataProvider()
    symbols = tuple(a.symbols or CORE)
    rep = evaluate(provider.daily_bars(symbols, months=a.months), provider.fictional)  # type: ignore[attr-defined]
    print(render(rep))
    if a.json:
        with open(a.json, "w") as fh:
            json.dump(rep, fh, indent=2, default=str)
    if a.save_db:
        from .store import Store
        Store(a.save_db).set_state("lab_latest", json.dumps(rep, default=str))
        print(f"Saved to {a.save_db}: the dashboard Research page now shows it.")


if __name__ == "__main__":
    main()
