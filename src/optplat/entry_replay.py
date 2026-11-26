"""Entry replay: compare followed candidates that pass an entry rule with those that do not, under the frozen 40/30 exit.

Evolution plan Phase 1 (ground truth) feeding Phase 2. It gives hypotheses E1 (spread 5% vs 10%), E2 (low vs high IV for the
name), E3 (45-90 vs 30-120 days to expiry), E4 (skip entries within 7 days of earnings), E6 (calls after vs before earnings), S1 (top-ranked vs the rest of the
ranked list) and R1 (regime guard) their outcome table. Measurement only: nothing here places an order or changes a rule.

Fixed before any result exists:

* The outcome of every follow is the baseline exit replay (``exit_replay.BASELINE``) on its recorded bid path: ask in, bid out,
  plus the stressed exit. Unresolved paths are counted and left out, never guessed. Follows with an unknown feature are left
  out of that hypothesis (counted as ``unknown``), never assigned to a group.
* Each group is reduced to independent observations (one per underlying per day, ``shadow.one_per_underlying_day``).
* The comparison is on the **later 30% of dates** of the observations used, difference of group means, 95% bootstrap interval
  of the difference, and the difference after dropping the treatment group's three best observations. All three must be
  positive for ``plan_bar_mechanical``. Sample minimums and the count of hypotheses tried (a stricter bar) are applied by the
  owner at registration; every group definition here counts as one hypothesis tried.
* Groups are definitions, not tuning: change one only by adding a new hypothesis.
"""
from __future__ import annotations

import random
from datetime import date
from typing import Any, Callable, Optional

from .exit_replay import BASELINE, BOOTSTRAP_RESAMPLES, BOOTSTRAP_SEED, LATER_FRACTION, _group_points, _path_key, replay_path
from .shadow import is_callout, one_per_underlying_day

MIN_PER_GROUP = 4  # fewer than this in either group on the later dates and no statement is made

Pick = Callable[[dict[str, Any]], Optional[bool]]  # True = treatment, False = control, None = unknown / not in this test


def _num(f: dict[str, Any], k: str) -> Optional[float]:
    v = f.get(k)
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def e1(f: dict[str, Any]) -> Optional[bool]:  # spread 5% or less vs 5-10%
    s = _num(f, "spread_pct")
    return None if s is None or s > 10 else s <= 5


def e2(f: dict[str, Any]) -> Optional[bool]:  # IV percentile for the name: low (30 or below) vs the rest
    p = _num(f, "iv_percentile")
    return None if p is None else p <= 30


def e3(f: dict[str, Any]) -> Optional[bool]:  # 45-90 days vs the rest of 30-120
    d = _num(f, "dte")
    return None if d is None or not 30 <= d <= 120 else 45 <= d <= 90


def e4(f: dict[str, Any]) -> Optional[bool]:  # treatment = not within 7 days of earnings; control = within 7 days (known dates only)
    d = _num(f, "days_to_earnings")
    return None if d is None or d < 0 else d > 7


def e6(f: dict[str, Any]) -> Optional[bool]:  # calls only: treatment = 1-3 days AFTER a report; control = 0-7 days BEFORE the next one
    if str(f.get("right")) != "C":
        return None
    after, before = _num(f, "days_since_earnings"), _num(f, "days_to_earnings")
    if after is not None and 1 <= after <= 3:
        return True
    return False if before is not None and 0 <= before <= 7 else None


def r1(f: dict[str, Any]) -> Optional[bool]:  # treatment = the guard would NOT have blocked this side; control = it would have
    key = {"P": "regime_blocks_puts", "C": "regime_blocks_calls"}.get(str(f.get("right")))
    v = f.get(key) if key else None
    return None if not isinstance(v, bool) else not v


def s1(f: dict[str, Any]) -> Optional[bool]:  # rank 1 of a strategy's list vs rank 2 or lower (lane picks and untagged follows are not in this test)
    ranks = [t.get("rank") for t in f.get("chosen_by", []) if not str(t.get("strategy", "")).startswith("lane:") and isinstance(t.get("rank"), int)]
    return None if not ranks else min(ranks) == 1


HYPOTHESES: dict[str, tuple[str, Pick]] = {
    "E1": ("spread 5% or less beats spread 5-10%", e1),
    "E2": ("IV percentile 30 or below beats higher", e2),
    "E3": ("45-90 days to expiry beats the rest of 30-120", e3),
    "E4": ("no earnings within 7 days beats earnings within 7 days", e4),
    "E6": ("calls bought 1-3 days after earnings beat calls bought within 7 days before (not split by the 10% run-up/fall: pre-report return not recorded)", e6),
    "S1": ("rank 1 of a strategy list beats ranks 2 and lower", s1),
    "R1": ("entries the regime guard would allow beat the ones it would block", r1),
}


def outcomes(follows: list[dict[str, Any]], points: list[dict[str, Any]], today: date) -> list[dict[str, Any]]:
    """Baseline-exit replay of every follow (not yet reduced to independent observations); the follow's own fields ride along."""
    paths = _group_points(points)
    out = []
    for f in follows:
        if is_callout(f):
            continue
        row = replay_path(BASELINE, f, paths.get(_path_key(f["contract"], f["followed_day"]), []), today)
        out.append({**f, **{k: row[k] for k in row if k not in ("contract", "symbol", "followed_day")}})
    return out


def _ci_diff(a: list[float], b: list[float]) -> tuple[float, float]:
    rng = random.Random(BOOTSTRAP_SEED)
    diffs = sorted(sum(a[rng.randrange(len(a))] for _ in a) / len(a) - sum(b[rng.randrange(len(b))] for _ in b) / len(b)
                   for _ in range(BOOTSTRAP_RESAMPLES))
    return diffs[int(0.025 * BOOTSTRAP_RESAMPLES)], diffs[int(0.975 * BOOTSTRAP_RESAMPLES) - 1]


def compare_hypothesis(hid: str, rows: list[dict[str, Any]], key: str = "ret_stressed") -> dict[str, Any]:
    """Compare treatment with control for one hypothesis over replayed rows (from ``outcomes``)."""
    statement, pick = HYPOTHESES[hid]
    groups: dict[bool, list[dict[str, Any]]] = {True: [], False: []}
    unknown = 0
    for r in rows:
        g = pick(r)
        if g is None:
            unknown += 1
        else:
            groups[g].append(r)
    obs = {g: one_per_underlying_day(v) for g, v in groups.items()}
    done = {g: [r for r in v if r.get("resolved")] for g, v in obs.items()}
    days = sorted({r["followed_day"] for v in done.values() for r in v})
    k = max(1, round(len(days) * LATER_FRACTION)) if days else 0
    later = set(days[len(days) - k:]) if k else set()
    t = sorted(r[key] for r in done[True] if r["followed_day"] in later)
    c = [r[key] for r in done[False] if r["followed_day"] in later]
    out: dict[str, Any] = {
        "hypothesis": hid, "statement": statement, "metric": key, "unknown_feature": unknown,
        "independent": {"treatment": len(obs[True]), "control": len(obs[False])},
        "resolved": {"treatment": len(done[True]), "control": len(done[False])},
        "later_dates": sorted(later), "later_observations": {"treatment": len(t), "control": len(c)}}
    if min(len(t), len(c)) < MIN_PER_GROUP:
        return {**out, "mean_diff_pct": None, "ci95_pct": None, "mean_diff_without_top3_pct": None, "plan_bar_mechanical": False,
                "note": f"too few resolved independent observations on the later dates (need {MIN_PER_GROUP} in each group)"}
    lo, hi = _ci_diff(t, c)
    mc = sum(c) / len(c)
    mean = sum(t) / len(t) - mc
    trimmed = t[:-3]
    t_mean = (sum(trimmed) / len(trimmed) - mc) if trimmed else None
    return {**out, "mean_diff_pct": round(mean * 100, 2), "ci95_pct": [round(lo * 100, 2), round(hi * 100, 2)],
            "mean_diff_without_top3_pct": None if t_mean is None else round(t_mean * 100, 2),
            "plan_bar_mechanical": bool(t_mean is not None and mean > 0 and lo > 0 and t_mean > 0),
            "note": "Mechanical check of the plan's bar only; not proof of an edge. Groups are unpaired, so contract mix can differ between them."}


def report(store: Any, fictional: bool, today: date) -> dict[str, Any]:
    rows = outcomes(store.shadow_all_follows(fictional), store.shadow_all_points(fictional), today)
    return {"fictional": fictional, "hypotheses_tried": len(HYPOTHESES), "followed": len(rows),
            "results": [compare_hypothesis(h, rows) for h in HYPOTHESES],
            "note": "Entry rules compared on recorded bid paths under the frozen 40/30 exit, one observation per underlying per day. "
                    "Every hypothesis shown counts towards a stricter bar. Simulated data when fictional is true; nothing here is proof of an edge."}
