"""Strategy evaluation over recorded data: measurements, never a verdict.

Runs the real engine over recorded snapshots (see ``replay``) in two independent time segments, an earlier
in-sample part and a later out-of-sample part, each from a fresh paper account. Nothing is tuned here, so the
split is a stability check: a result that exists only in one half deserves suspicion.

Numbers are only labelled MEASURED when there are enough closed trades in total and in the out-of-sample
part. Otherwise they are descriptive and the status says INSUFFICIENT_DATA. Fictional data is always labelled
meaningless. Nothing here says a strategy has an edge.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional, Sequence

from .replay import ReplayResult, run_replay
from .risk import RiskPolicy
from .strategy import Strategy

MIN_TRADES = 30
MIN_OOS_TRADES = 10
OOS_FRACTION = 0.3

CAVEATS = [
    "Paper results on simulated fills (buys at ask plus slippage, sells at bid minus slippage). Real fills differ.",
    "Recorded free data is delayed and unofficial, and the recorded period is one market regime.",
    "No commissions, fees or taxes are modelled.",
    "Each segment starts from a fresh account, so a position open at the split is not carried across.",
    "These are measurements, not proof of an edge. Past paper results predict nothing by themselves.",
]


def _max_drawdown_pct(equity: Sequence[float], start: float) -> float:
    peak, worst = start, 0.0
    for e in equity:
        peak = max(peak, e)
        if peak > 0:
            worst = max(worst, (peak - e) / peak * 100)
    return round(worst, 2)


def equity_summary(points: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """Peak, drawdowns and change from the first point, for the equity chart's headline numbers."""
    values = [float(p["equity"]) for p in points]
    if not values:
        return {"points": 0, "start": None, "last": None, "change_pct": None, "peak": None,
                "current_drawdown_pct": None, "max_drawdown_pct": None}
    peak = max(values)
    return {
        "points": len(values), "start": values[0], "last": values[-1],
        "change_pct": round((values[-1] - values[0]) / values[0] * 100, 3) if values[0] else None,
        "peak": peak, "current_drawdown_pct": round((peak - values[-1]) / peak * 100, 2) if peak > 0 else None,
        "max_drawdown_pct": _max_drawdown_pct(values, values[0]),
    }


def _segment(name: str, rows: Sequence[dict[str, Any]], **replay_kwargs: Any) -> dict[str, Any]:
    result: ReplayResult = run_replay(rows, **replay_kwargs)
    rep = result.report
    closed = rep["closed_trades"]
    start_equity = 100_000.0  # the simulated broker's starting account
    end_equity = result.equity[-1] if result.equity else start_equity
    return {
        "name": name,
        "from": result.trace[0][0],
        "to": result.trace[-1][0],
        "steps": result.steps,
        "closed_trades": closed,
        "win_rate_pct": rep["win_rate_pct"],
        "realized_pnl": rep["realized_pnl"],
        "expectancy_per_trade": round(rep["realized_pnl"] / closed, 2) if closed else None,
        "open_positions_at_end": len(rep["open"]),
        "return_pct": round((end_equity - start_equity) / start_equity * 100, 3),
        "max_drawdown_pct": _max_drawdown_pct(result.equity, start_equity),
        "fictional": result.fictional,
    }


def _buy_and_hold(rows: Sequence[dict[str, Any]]) -> dict[str, float]:
    """Percent move of each underlying between its first and last recorded snapshot (context only)."""
    first: dict[str, tuple[str, float]] = {}
    last: dict[str, tuple[str, float]] = {}
    for r in rows:
        at, px = r["recorded_at"], float(r["payload"]["underlying"])
        sym = r["symbol"]
        if sym not in first or at < first[sym][0]:
            first[sym] = (at, px)
        if sym not in last or at >= last[sym][0]:
            last[sym] = (at, px)
    return {s: round((last[s][1] - first[s][1]) / first[s][1] * 100, 2) for s in sorted(first) if first[s][1] > 0}


def evaluate(
    rows: Sequence[dict[str, Any]],
    *,
    strategy: Optional[Strategy] = None,
    config: Optional[dict[str, Any]] = None,
    policy: Optional[RiskPolicy] = None,
    min_trades: int = MIN_TRADES,
    min_oos_trades: int = MIN_OOS_TRADES,
    oos_fraction: float = OOS_FRACTION,
) -> dict[str, Any]:
    if not rows:
        raise ValueError("No recorded snapshots to evaluate")
    if not 0.1 <= oos_fraction <= 0.5:
        raise ValueError("oos_fraction must be between 0.1 and 0.5")
    moments = sorted({r["recorded_at"] for r in rows}, key=datetime.fromisoformat)
    if len(moments) < 4:
        raise ValueError("Need at least 4 recorded moments to split into in-sample and out-of-sample")
    cut = moments[max(2, min(len(moments) - 2, int(len(moments) * (1 - oos_fraction))))]
    key = datetime.fromisoformat
    early = [r for r in rows if key(r["recorded_at"]) < key(cut)]
    late = [r for r in rows if key(r["recorded_at"]) >= key(cut)]

    kwargs = {"strategy": strategy, "config": config, "policy": policy}
    segments = [_segment("in_sample", early, **kwargs), _segment("out_of_sample", late, **kwargs)]
    total = sum(s["closed_trades"] for s in segments)
    oos = segments[1]["closed_trades"]
    fictional = any(bool(r["fictional"]) for r in rows)

    reasons: list[str] = []
    if total < min_trades:
        reasons.append(f"{total} closed trades in total; at least {min_trades} are needed")
    if oos < min_oos_trades:
        reasons.append(f"{oos} closed trades out of sample; at least {min_oos_trades} are needed")
    if fictional:
        status, reasons = "FICTIONAL_DATA", ["The data is fictional, so the numbers mean nothing"] + reasons
    elif reasons:
        status = "INSUFFICIENT_DATA"
    else:
        status = "MEASURED"
    return {
        "status": status,
        "reasons": reasons,
        "segments": segments,
        "do_nothing": {"return_pct": 0.0, "max_drawdown_pct": 0.0, "closed_trades": 0},
        "underlying_buy_and_hold_pct": _buy_and_hold(rows),
        "recorded_moments": len(moments),
        "caveats": CAVEATS,
    }


def _pct(value: Optional[float]) -> str:
    return "n/a" if value is None else f"{value}%"


def format_report(result: dict[str, Any]) -> str:
    lines = [f"STATUS: {result['status']}"]
    lines += [f"  - {r}" for r in result["reasons"]]
    if result["status"] != "MEASURED":
        lines.append("  The figures below are descriptive only. Do not treat them as a result.")
    lines.append(f"Recorded moments replayed: {result['recorded_moments']}")
    for seg in result["segments"]:
        lines.append(
            f"\n{seg['name']}  ({seg['from'][:19]} -> {seg['to'][:19]}, {seg['steps']} steps)\n"
            f"  closed trades {seg['closed_trades']}, win rate {_pct(seg['win_rate_pct'])}, realized P&L {seg['realized_pnl']},"
            f" per trade {seg['expectancy_per_trade'] if seg['expectancy_per_trade'] is not None else 'n/a'}\n"
            f"  return {seg['return_pct']}%, max drawdown {seg['max_drawdown_pct']}%,"
            f" positions still open {seg['open_positions_at_end']}"
        )
    lines.append("\nDo nothing: return 0.0%, drawdown 0.0%, no trades.")
    hold = ", ".join(f"{s} {p:+.2f}%" for s, p in result["underlying_buy_and_hold_pct"].items())
    lines.append(f"Underlying buy-and-hold over the whole period (context only): {hold}")
    lines.append("\nCaveats:")
    lines += [f"  * {c}" for c in result["caveats"]]
    return "\n".join(lines)
