"""Exit replay harness: replay exit rules over the shadow book's recorded bid paths.

Evolution plan, Phase 1 item 3. It helps hypotheses X1 (take-profit/stop grid), X2 (time stop) and X3 (trailing stop),
and gives E1-E5 an outcome to compare. Measurement only: nothing here places an order, changes a threshold or promotes a rule.

Honesty rules, all fixed before any result exists:

* Entry is the recorded ask, exit the recorded bid at the first path point where the rule fires. A rule that "would have
  sold at +40%" sells at the bid of the point where it was seen, which may be better or worse than 40%. A gap is a gap.
* Within one point the stop is checked before the take-profit (the pessimistic order).
* A **stressed** exit is also reported: bid minus half the recorded spread at that point.
* A path that has not fired a rule, has not reached the 30 trading day horizon and whose contract has not expired is
  **unresolved**. It is counted and left out of every average, never filled with a guess.
* One observation per underlying per day (``shadow.one_per_underlying_day``) is the sample; strikes of one name are not
  counted as separate trades.
* ``compare`` applies the plan's mechanical bar (positive on the later 30% of dates, 95% bootstrap interval above zero,
  positive after dropping the three best observations). The sample minimums and the count of hypotheses tried, which
  make the bar stricter, are applied by ``research.py`` and the owner, not here. Passing it is not proof of an edge.
"""
from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import date
from typing import Any, Optional

from . import robustness
from .exits import ExitPolicy
from .shadow import MAX_AGE, one_per_underlying_day

LATER_FRACTION = 0.3
BOOTSTRAP_RESAMPLES = 2000
BOOTSTRAP_SEED = 20261117


@dataclass(frozen=True)
class ExitRule:
    """Percent levels are on the option price versus the ask paid. ``None`` disables a part."""
    name: str
    take_profit_pct: Optional[float] = None
    stop_loss_pct: Optional[float] = None
    time_stop_days: Optional[int] = None          # trading days after the follow
    trail_after_pct: Optional[float] = None       # arm the trail once the return has reached this
    trail_pct: Optional[float] = None             # then exit when the return falls this many points below its peak
    min_dte_to_hold: int = 5                      # leave before expiry gets dangerous (same as the live policy)
    trim_at_pct: Optional[float] = None           # X5: sell ``trim_fraction`` once the return has reached this, then stop to entry
    trim_fraction: float = 0.5                    # share sold at the trim; the rest keeps the take-profit and a stop at entry (0%)


_P = ExitPolicy()
BASELINE = ExitRule("baseline 40/30", take_profit_pct=_P.take_profit_pct, stop_loss_pct=_P.stop_loss_pct, min_dte_to_hold=_P.min_dte_to_hold)


def grid_rules() -> list[ExitRule]:
    """X1, X2 and X3 as registered in the evolution plan (the baseline is included as the reference)."""
    rules = [BASELINE]
    for tp in (20, 40, 80):
        for sl in (20, 30, 50):
            if (tp, sl) != (_P.take_profit_pct, _P.stop_loss_pct):
                rules.append(ExitRule(f"tp{tp}/sl{sl}", take_profit_pct=tp, stop_loss_pct=sl))
    for d in (5, 10):
        rules.append(ExitRule(f"40/30 + time stop {d}d", take_profit_pct=40, stop_loss_pct=30, time_stop_days=d))
    rules.append(ExitRule("trail 30/15, stop 30", stop_loss_pct=30, trail_after_pct=30, trail_pct=15))
    for t in (20, 40):  # X5: trim half, move the stop to entry, let the rest run to 80
        rules.append(ExitRule(f"X5 trim 1/2 at +{t}, stop to entry, tp 80", take_profit_pct=80, stop_loss_pct=30, trim_at_pct=t))
    return rules


def _path_key(contract: str, day: str) -> tuple[str, str]:
    return contract, day


def _group_points(points: list[dict[str, Any]]) -> dict[tuple[str, str], list[dict[str, Any]]]:
    paths: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for p in points:
        paths.setdefault(_path_key(p["contract"], p["followed_day"]), []).append(p)
    for v in paths.values():
        v.sort(key=lambda p: p.get("ts") or "")
    return paths


def _stressed(point: dict[str, Any], entry: float) -> float:
    bid, ask = point["bid"], point.get("ask")
    half = (ask - bid) / 2 if ask is not None and ask >= bid else 0.0
    return max(-1.0, (bid - half) / entry - 1)


def replay_path(rule: ExitRule, follow: dict[str, Any], path: list[dict[str, Any]], today: date) -> dict[str, Any]:
    """Replay one rule over one path. Returns a row with ``resolved`` False when the path cannot say what happened."""
    entry = follow.get("entry_ask")
    base = {"contract": follow["contract"], "symbol": follow["symbol"], "followed_day": follow["followed_day"]}
    if not entry or entry <= 0:
        return {**base, "resolved": False, "reason": "no_entry_ask"}
    expiry = date.fromisoformat(follow["expiry"])
    peak = 0.0
    last: Optional[dict[str, Any]] = None
    trim: Optional[tuple[float, float]] = None  # (ret, stressed ret) of the trimmed share, once sold

    def blend(ret: float, stressed: float) -> tuple[float, float]:
        if trim is None:
            return ret, stressed
        f = rule.trim_fraction
        return f * trim[0] + (1 - f) * ret, f * trim[1] + (1 - f) * stressed
    for p in path:
        if p.get("bid") is None or p["bid"] < 0:
            continue
        last = p
        ret = p["bid"] / entry - 1
        peak = max(peak, ret)
        observed = date.fromisoformat(p["observed_day"]) if p.get("observed_day") else None
        reason = None
        if trim is not None and ret <= 0:
            reason = "stop_to_entry"  # sold at this bid, which can be below entry on a gap
        elif trim is None and rule.stop_loss_pct is not None and ret <= -rule.stop_loss_pct / 100:
            reason = "stop"
        elif trim is None and rule.trim_at_pct is not None and ret >= rule.trim_at_pct / 100 \
                and not (rule.take_profit_pct is not None and ret >= rule.take_profit_pct / 100):
            trim = (ret, _stressed(p, entry))
            continue
        elif rule.take_profit_pct is not None and ret >= rule.take_profit_pct / 100:
            reason = "take_profit"
        elif rule.trail_after_pct is not None and rule.trail_pct is not None and peak >= rule.trail_after_pct / 100 \
                and ret <= peak - rule.trail_pct / 100:
            reason = "trail"
        elif rule.time_stop_days is not None and p["age"] >= rule.time_stop_days:
            reason = "time_stop"
        elif observed is not None and (expiry - observed).days <= rule.min_dte_to_hold:
            reason = "expiry_margin"
        if reason:
            r, rs = blend(ret, _stressed(p, entry))
            return {**base, "resolved": True, "reason": reason, "ret": r, "ret_stressed": rs, "age": p["age"]}
    if last is not None and (last["age"] >= MAX_AGE or expiry < today):
        r, rs = blend(last["bid"] / entry - 1, _stressed(last, entry))
        return {**base, "resolved": True, "reason": "horizon", "ret": r, "ret_stressed": rs, "age": last["age"]}
    return {**base, "resolved": False, "reason": "unresolved"}


def replay(rule: ExitRule, follows: list[dict[str, Any]], points: list[dict[str, Any]], today: date) -> list[dict[str, Any]]:
    """Replay a rule over the independent observations (one per underlying per day)."""
    paths = _group_points(points)
    return [replay_path(rule, f, paths.get(_path_key(f["contract"], f["followed_day"]), []), today) for f in one_per_underlying_day(follows)]


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    done = [r for r in rows if r["resolved"]]
    reasons: dict[str, int] = {}
    for r in done:
        reasons[r["reason"]] = reasons.get(r["reason"], 0) + 1
    n = len(done)
    return {"observations": len(rows), "resolved": n, "unresolved": len(rows) - n, "reasons": reasons,
            "mean_return_pct": round(sum(r["ret"] for r in done) / n * 100, 2) if n else None,
            "mean_return_stressed_pct": round(sum(r["ret_stressed"] for r in done) / n * 100, 2) if n else None,
            "win_rate_pct": round(sum(1 for r in done if r["ret"] > 0) / n * 100, 1) if n else None,
            "mean_age_days": round(sum(r["age"] for r in done) / n, 1) if n else None}


def later_days(rows: list[dict[str, Any]]) -> set[str]:
    """The latest 30% of followed days (at least one), the part not used to pick the idea."""
    days = sorted({r["followed_day"] for r in rows})
    k = max(1, round(len(days) * LATER_FRACTION)) if days else 0
    return set(days[len(days) - k:]) if k else set()


def _bootstrap_ci(values: list[float]) -> tuple[float, float]:
    rng = random.Random(BOOTSTRAP_SEED)
    n = len(values)
    means = sorted(sum(values[rng.randrange(n)] for _ in range(n)) / n for _ in range(BOOTSTRAP_RESAMPLES))
    return means[int(0.025 * BOOTSTRAP_RESAMPLES)], means[int(0.975 * BOOTSTRAP_RESAMPLES) - 1]


def compare(challenger: list[dict[str, Any]], baseline: list[dict[str, Any]], key: str = "ret_stressed") -> dict[str, Any]:
    """Paired difference (challenger minus baseline) on the later 30% of dates, over observations both rules resolved.

    ``key`` defaults to the stressed return, the stricter of the two. Returns the numbers and ``plan_bar_mechanical``;
    it never says "edge".
    """
    base = {(r["contract"], r["followed_day"]): r for r in baseline if r["resolved"]}
    pairs = [(c, base[(c["contract"], c["followed_day"])]) for c in challenger if c["resolved"] and (c["contract"], c["followed_day"]) in base]
    later = later_days([c for c, _ in pairs])
    diffs = sorted(c[key] - b[key] for c, b in pairs if c["followed_day"] in later)
    out: dict[str, Any] = {"metric": key, "paired": len(pairs), "later_observations": len(diffs), "later_days": sorted(later)}
    if len(diffs) < 4:  # too few to bootstrap or trim three; say so instead of guessing
        return {**out, "mean_diff_pct": None, "ci95_pct": None, "mean_diff_without_top3_pct": None, "plan_bar_mechanical": False,
                "note": "too few paired observations on the later dates"}
    lo, hi = _bootstrap_ci(diffs)
    mean = sum(diffs) / len(diffs)
    trimmed = diffs[:-3]
    t_mean = sum(trimmed) / len(trimmed)
    passed = mean > 0 and lo > 0 and t_mean > 0
    paired = [(c["followed_day"], c[key] - b[key]) for c, b in pairs]
    robust = robustness.check([p for p in paired if p[0] in later], paired, passed, scale=100)
    return {**out, "mean_diff_pct": round(mean * 100, 2), "ci95_pct": [round(lo * 100, 2), round(hi * 100, 2)],
            "mean_diff_without_top3_pct": round(t_mean * 100, 2), "plan_bar_mechanical": passed, "robustness": robust,
            "note": "Mechanical check of the plan's bar only. Sample minimums and the number of rules tried (a stricter bar) are applied at registration."}


def report(store: Any, fictional: bool, today: date) -> dict[str, Any]:
    follows, points = store.shadow_all_follows(fictional), store.shadow_all_points(fictional)
    base_rows = replay(BASELINE, follows, points, today)
    rules = []
    for rule in grid_rules():
        rows = base_rows if rule is BASELINE else replay(rule, follows, points, today)
        rules.append({"rule": rule.name, **summarize(rows), "vs_baseline_later_30pct": None if rule is BASELINE else compare(rows, base_rows)})
    return {"fictional": fictional, "rules_tried": len(rules) - 1, "rules": rules,
            "note": "Replay over recorded bid paths, entry at the ask, exit at the bid (stressed: bid minus half the spread). One observation per underlying per day. "
                    "Exploratory: rules are only registered as hypotheses through research.py, and every rule tried here counts towards a stricter bar. "
                    "Simulated data when fictional is true; nothing here is proof of an edge."}
