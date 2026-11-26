"""Two checks that sit beside every registered pass rule and never change its verdict.

The registered rules resample single observations as if each were independent. Observations opened on the same
market day are not: one move in the index lifts or sinks them together, so that interval is too narrow and a lucky
week can pass. Borrowed from BijectiveLabs' falsification chain (layer 5), each result also carries:

* ``ci_day_clustered``: the same interval, resampling whole days (every observation of a drawn day comes along).
* ``subperiods``: the mean in each of three consecutive blocks of days. An edge that lives in one block is a
  condition, not an edge.

``warning`` is set when the registered rule passes but either check disagrees. The verdicts stay as registered:
changing a pass rule after registration would undo pre-registration. Seeded and deterministic.
"""
from __future__ import annotations

import random
from typing import Any, Iterable, Optional, Sequence

RESAMPLES = 2000
SEED = 20261127
BLOCKS = 3


def _by_day(rows: Iterable[tuple[str, float]]) -> dict[str, list[float]]:
    out: dict[str, list[float]] = {}
    for day, v in rows:
        out.setdefault(day, []).append(v)
    return out


def day_clustered_ci(rows: Sequence[tuple[str, float]], alpha: float = 0.05,
                     baseline: Sequence[tuple[str, float]] = ()) -> Optional[tuple[float, float]]:
    """Interval for mean(rows) - mean(baseline) (baseline empty: just the mean), resampling days. None if under 2 days."""
    a, b = _by_day(rows), _by_day(baseline)
    days = sorted(set(a) | set(b))
    if len(days) < 2 or not a:
        return None
    rng = random.Random(SEED)
    stats = []
    for _ in range(RESAMPLES):
        pick = [days[rng.randrange(len(days))] for _ in days]
        xa = [v for d in pick for v in a.get(d, ())]
        if not xa:
            continue
        m = sum(xa) / len(xa)
        if b:
            xb = [v for d in pick for v in b.get(d, ())]
            if not xb:
                continue
            m -= sum(xb) / len(xb)
        stats.append(m)
    if len(stats) < RESAMPLES // 2:
        return None
    stats.sort()
    k = int(alpha / 2 * len(stats))
    return stats[k], stats[len(stats) - 1 - k]


def subperiod_means(rows: Sequence[tuple[str, float]], blocks: int = BLOCKS,
                    baseline: Sequence[tuple[str, float]] = ()) -> Optional[list[Optional[float]]]:
    """Mean (minus the baseline's, if given) per consecutive block of days, days split as evenly as possible. A block
    where either group has nothing is None. None overall if there are fewer days than blocks."""
    a, b = _by_day(rows), _by_day(baseline)
    days = sorted(set(a) | set(b))
    if len(days) < blocks or not a:
        return None
    out: list[Optional[float]] = []
    for i in range(blocks):
        chunk = days[i * len(days) // blocks:(i + 1) * len(days) // blocks]
        xa = [v for d in chunk for v in a.get(d, ())]
        xb = [v for d in chunk for v in b.get(d, ())]
        if not xa or (b and not xb):
            out.append(None)
            continue
        out.append(sum(xa) / len(xa) - (sum(xb) / len(xb) if b else 0.0))
    return out


def check(later: Sequence[tuple[str, float]], whole: Sequence[tuple[str, float]], passed: bool, *, alpha: float = 0.05,
          later_baseline: Sequence[tuple[str, float]] = (), whole_baseline: Sequence[tuple[str, float]] = (),
          scale: float = 1.0) -> dict[str, Any]:
    """The robustness fields for one result. ``later`` drives the interval (as the registered rule does), ``whole``
    the subperiods. ``scale`` converts to the result's own units (100 for fractions shown as percent)."""
    ci = day_clustered_ci(later, alpha, later_baseline)
    subs = subperiod_means(whole, baseline=whole_baseline)
    out: dict[str, Any] = {
        "ci_day_clustered": None if ci is None else [round(ci[0] * scale, 3), round(ci[1] * scale, 3)],
        "ci_level": 1 - alpha,
        "subperiod_means": None if subs is None else [None if v is None else round(v * scale, 3) for v in subs],
        "warning": None,
    }
    if passed:
        why = []
        if ci is None or ci[0] <= 0:
            why.append("the interval resampled by whole days includes zero (same-day observations move together)")
        if subs is None or sum(1 for v in subs if v is not None and v > 0) < BLOCKS - 1:
            why.append(f"the mean is not positive in at least {BLOCKS - 1} of {BLOCKS} consecutive blocks of days")
        if why:
            out["warning"] = "Passes the registered rule, but " + "; and ".join(why) + ". Treat as not yet robust."
    return out
