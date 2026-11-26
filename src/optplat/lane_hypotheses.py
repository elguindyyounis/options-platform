"""Registered hypotheses SW1 (swing lane) and ST1 (short-term lane), with their pass criteria fixed in code.

Evolution plan, Phase 2. Registered 2026-11-26 on the owner's instruction ("register the swing and short-term lanes
as pre-registered experiments with pass criteria", criteria delegated to the agent). Measurement only: nothing here
places an order, opens or closes a lane trade, changes a lane's rule or promotes anything.

Rules fixed before any confirmatory result exists:

* **Confirmatory sample only.** A trade counts only if it OPENED on or after ``first_day`` (the first session after
  registration). Every earlier trade was already visible when these criteria were written, so it is ignored.
* **Fixed sample, one verdict.** The verdict is taken on the first ``sample`` independent observations in date order
  and on nothing else. More trades later cannot change it, so there is no re-checking until a pass appears.
* **Independent observations.** One per underlying per New York entry day (the mean of that name's trades that day).
* **Costs.** Recorded fills already carry the lane's slippage (0.05% each way). A further ``stress_pct`` is subtracted
  from every trade's return.
* **SW1 baseline is SPY.** A swing trade's observation is its return minus SPY's close-to-close return over the same
  New York dates. A trade whose SPY dates are missing is unmatched; more than 10% unmatched means no verdict.
* **ST1 baseline is zero.** An intraday long has a market drift of about zero, so the bar is positive net expectancy.
* **The bar** (the plan's, made stricter for the two hypotheses tested together): the mean over the later 30% of
  dates is positive and its two-sided bootstrap interval at 1 - 0.05/2 excludes zero, and the mean over the whole
  fixed sample is still positive after dropping its three best observations.
* "PASSED_CRITERIA" means the bar was met on this sample. It is not proof of an edge; promotion stays the owner's.
"""
from __future__ import annotations

import argparse
import json
import random
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Mapping, Optional, Sequence

from .market_clock import NY

LATER_FRACTION = 0.3
BOOTSTRAP_RESAMPLES = 4000
BOOTSTRAP_SEED = 20261126
FAMILY_SIZE = 2                  # SW1 and ST1 are tested together: Bonferroni over the two
MAX_UNMATCHED_SHARE = 0.10


@dataclass(frozen=True)
class LaneHypothesis:
    hid: str
    lane: str
    statement: str
    first_day: date              # first New York session whose entries count
    sample: int                  # independent observations in the fixed sample
    min_symbols: int
    min_days: int
    stress_pct: float            # extra cost per trade, percent of entry
    vs_spy: bool


SW1 = LaneHypothesis(
    "SW1", "swing-pullback",
    "The swing pullback lane's trades beat SPY over the same dates, after costs.",
    date(2026, 11, 27), sample=60, min_symbols=20, min_days=15, stress_pct=0.20, vs_spy=True)
ST1 = LaneHypothesis(
    "ST1", "shortterm-ema9-vwap",
    "The short-term EMA9/VWAP lane has positive expectancy per trade after costs.",
    date(2026, 11, 27), sample=100, min_symbols=4, min_days=20, stress_pct=0.10, vs_spy=False)
REGISTERED = (SW1, ST1)


def _ny_day(stamp: str) -> date:
    at = datetime.fromisoformat(stamp)
    if at.tzinfo is None:
        raise ValueError("lane trade time without a timezone")
    return at.astimezone(NY).date()


def _close_on_or_before(closes: Mapping[date, float], day: date) -> Optional[float]:
    """The last close at or before ``day`` within five calendar days (a weekend or holiday), else None."""
    for back in range(6):
        d = date.fromordinal(day.toordinal() - back)
        if d in closes:
            return closes[d]
    return None


def observations(h: LaneHypothesis, trades: Sequence[dict[str, Any]],
                 spy_close: Optional[Mapping[date, float]] = None) -> tuple[list[dict[str, Any]], int, int]:
    """(independent observations in date order, trades used, trades unmatched to SPY). Real closed trades only."""
    groups: dict[tuple[str, date], list[float]] = {}
    used = unmatched = 0
    for t in trades:
        if t.get("lane") != h.lane or t.get("fictional") or not t.get("closed_at") or t.get("exit_price") is None:
            continue
        entry, exit_ = float(t["entry_price"]), float(t["exit_price"])
        day = _ny_day(t["opened_at"])
        if day < h.first_day or not entry > 0 or not exit_ > 0:
            continue
        ret = (exit_ / entry - 1) * 100 - h.stress_pct
        if h.vs_spy:
            a = _close_on_or_before(spy_close or {}, day)
            b = _close_on_or_before(spy_close or {}, _ny_day(t["closed_at"]))
            if a is None or b is None or not a > 0:
                unmatched += 1
                continue
            ret -= (b / a - 1) * 100
        used += 1
        groups.setdefault((t["symbol"], day), []).append(ret)
    obs = [{"symbol": s, "day": d.isoformat(), "ret_pct": sum(v) / len(v)} for (s, d), v in groups.items()]
    obs.sort(key=lambda o: (o["day"], o["symbol"]))
    return obs, used, unmatched


def _bootstrap_ci(values: list[float], alpha: float) -> tuple[float, float]:
    rng = random.Random(BOOTSTRAP_SEED)
    n = len(values)
    means = sorted(sum(values[rng.randrange(n)] for _ in range(n)) / n for _ in range(BOOTSTRAP_RESAMPLES))
    lo = int(alpha / 2 * BOOTSTRAP_RESAMPLES)
    return means[lo], means[BOOTSTRAP_RESAMPLES - 1 - lo]


def evaluate(h: LaneHypothesis, trades: Sequence[dict[str, Any]],
             spy_close: Optional[Mapping[date, float]] = None) -> dict[str, Any]:
    obs, used, unmatched = observations(h, trades, spy_close)
    out: dict[str, Any] = {"id": h.hid, "lane": h.lane, "statement": h.statement, "first_day": h.first_day.isoformat(),
                           "sample_required": h.sample, "observations": len(obs), "trades_used": used,
                           "trades_unmatched": unmatched}
    if used + unmatched and unmatched / (used + unmatched) > MAX_UNMATCHED_SHARE:
        return {**out, "verdict": "NO_VERDICT_DATA", "note": "too many trades without SPY closes for their dates"}
    if len(obs) < h.sample:
        return {**out, "verdict": "COLLECTING"}
    fixed = obs[:h.sample]
    days = sorted({o["day"] for o in fixed})
    symbols = {o["symbol"] for o in fixed}
    out.update(sample_from=days[0], sample_to=days[-1], sample_days=len(days), sample_symbols=len(symbols))
    if len(days) < h.min_days or len(symbols) < h.min_symbols:
        # The fixed sample is too concentrated to judge. It stays the sample: no waiting for a better one.
        return {**out, "verdict": "FAILED_CRITERIA", "reason": "fixed sample too concentrated in days or names"}
    k = max(1, round(len(days) * LATER_FRACTION))
    later_set = set(days[-k:])
    later = [o["ret_pct"] for o in fixed if o["day"] in later_set]
    alpha = 0.05 / FAMILY_SIZE
    lo, hi = _bootstrap_ci(later, alpha) if len(later) >= 4 else (float("nan"), float("nan"))
    rets = sorted(o["ret_pct"] for o in fixed)
    mean_later = sum(later) / len(later)
    mean_trim = sum(rets[:-3]) / (len(rets) - 3)
    passed = len(later) >= 4 and mean_later > 0 and lo > 0 and mean_trim > 0
    return {**out, "verdict": "PASSED_CRITERIA" if passed else "FAILED_CRITERIA",
            "mean_pct": round(sum(rets) / len(rets), 3), "later_days": len(later_set), "later_observations": len(later),
            "mean_later_pct": round(mean_later, 3), "ci_later_pct": [round(lo, 3), round(hi, 3)], "ci_level": 1 - alpha,
            "mean_without_top3_pct": round(mean_trim, 3),
            "note": "Mechanical check of pre-registered criteria on a fixed paper sample. Not proof of an edge."}


def report(store: Any, provider: Any = None) -> list[dict[str, Any]]:
    spy: dict[date, float] = {}
    if provider is not None:
        try:
            spy = {b.day: b.close for b in provider.daily_bars(["SPY"], months=12)["SPY"]}
        except Exception:  # noqa: BLE001 - no SPY closes means SW1 reports NO_VERDICT_DATA, never a guess
            spy = {}
    return [evaluate(h, store.lane_trades(h.lane, False, limit=2000), spy) for h in REGISTERED]


def main(argv: Optional[Sequence[str]] = None) -> None:
    ap = argparse.ArgumentParser(description="Evaluate registered lane hypotheses SW1 and ST1 (read-only).")
    ap.add_argument("--db", default="optplat.db")
    args = ap.parse_args(argv)
    from .marketdata import YahooDataProvider
    from .store import Store
    print(json.dumps(report(Store(args.db), YahooDataProvider()), indent=2))


if __name__ == "__main__":
    main()
