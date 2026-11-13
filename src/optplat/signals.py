"""Options signals, computed from one market snapshot, and a way to measure whether any of them predicts anything.

Nothing here trades. Every signal starts UNVALIDATED, and a strategy may not use one until its name is added to
``VALIDATED_SIGNALS`` by the owner after a study (``study_signal``) and a pre-registered experiment (``research``)
support it. ``use_signal`` enforces that.

Honest limits of the data these run on (free, delayed, unofficial):
* The chain in a snapshot is a SAMPLE, not every strike and expiry. Anything summed over the chain, GEX
  especially, is partial. ``coverage`` says how much was seen.
* Volume is the day's running total; open interest is the previous day's. Neither says who initiated a trade,
  so "unusual" means "large relative to open interest", not "bought by informed money".
* GEX needs an assumption about who holds what (here: customers long calls and short puts, so dealers short
  calls and long puts). That assumption is contested; it is stated in every result.
"""
from __future__ import annotations

import bisect
import math
from datetime import datetime, timedelta
from typing import Any, Callable, Optional, Sequence

from .dataquality import check_snapshot
from .marketdata import MarketSnapshot, snapshot_from_dict
from .models import Right
from .store import Store

VALIDATED_SIGNALS: frozenset[str] = frozenset()  # owner-edited: empty means no strategy may use any signal yet
SIGNAL_NAMES = ("call_put_volume_ratio", "call_put_oi_ratio", "unusual_count", "gex_total")

MIN_UNUSUAL_VOLUME = 100
MIN_UNUSUAL_OI = 50
MIN_VOLUME_TO_OI = 1.0
RATE = 0.0  # no risk-free rate is assumed: avoids false precision for a rough exposure estimate
MIN_STUDY_SAMPLE = 100  # observations overlap in time, so the effective sample is far smaller than this


class SignalNotValidated(Exception):
    pass


def use_signal(name: str) -> None:
    """Call this before a strategy reads a signal. It fails until the owner has validated the signal."""
    if name not in SIGNAL_NAMES:
        raise KeyError(f"Unknown signal {name!r}")
    if name not in VALIDATED_SIGNALS:
        raise SignalNotValidated(f"Signal {name!r} is UNVALIDATED: studied or pre-registered evidence is required first")


# ------------------------------------------------------------ math
def bs_gamma(spot: float, strike: float, t_years: float, vol: float, rate: float = RATE) -> Optional[float]:
    """Black-Scholes gamma (same for calls and puts). None when the inputs make it undefined."""
    if not all(math.isfinite(x) for x in (spot, strike, t_years, vol)) or min(spot, strike, t_years, vol) <= 0:
        return None
    d1 = (math.log(spot / strike) + (rate + vol * vol / 2) * t_years) / (vol * math.sqrt(t_years))
    return math.exp(-d1 * d1 / 2) / math.sqrt(2 * math.pi) / (spot * vol * math.sqrt(t_years))


# ------------------------------------------------------------ features
def coverage(snap: MarketSnapshot) -> dict[str, Any]:
    rows = snap.rows
    strikes = [r.contract.strike for r in rows]
    n = len(rows)
    return {
        "rows": n,
        "expiries": len({r.contract.expiry for r in rows}),
        "strike_range_pct_of_spot": [round((min(strikes) / snap.underlying - 1) * 100, 1),
                                     round((max(strikes) / snap.underlying - 1) * 100, 1)] if n else None,
        "pct_with_volume": round(100 * sum(r.volume is not None for r in rows) / n, 1) if n else 0.0,
        "pct_with_open_interest": round(100 * sum(r.open_interest is not None for r in rows) / n, 1) if n else 0.0,
        "pct_with_iv": round(100 * sum(r.iv is not None for r in rows) / n, 1) if n else 0.0,
    }


def liquidity_tier(spread_pct: float, volume: Optional[int], oi: Optional[int]) -> str:
    v, o = volume or 0, oi or 0
    if spread_pct <= 5 and v >= 100 and o >= 1000:
        return "A"
    if spread_pct <= 10 and v >= 50 and o >= 500:
        return "B"  # the baseline strategy's own filter
    return "C"


def liquidity(snap: MarketSnapshot) -> dict[str, int]:
    tiers = {"A": 0, "B": 0, "C": 0}
    for r in snap.rows:
        if r.ask > 0:
            tiers[liquidity_tier((r.ask - r.bid) / r.ask * 100, r.volume, r.open_interest)] += 1
    return tiers


def activity(snap: MarketSnapshot, top: int = 5) -> dict[str, Any]:
    cv = pv = coi = poi = 0
    unusual: list[dict[str, Any]] = []
    for r in snap.rows:
        vol, oi = r.volume or 0, r.open_interest or 0
        if r.contract.right is Right.CALL:
            cv, coi = cv + vol, coi + oi
        else:
            pv, poi = pv + vol, poi + oi
        if vol >= MIN_UNUSUAL_VOLUME and oi >= MIN_UNUSUAL_OI and vol / oi >= MIN_VOLUME_TO_OI:
            unusual.append({
                "contract": r.contract.occ_symbol.strip(), "volume": vol, "open_interest": oi,
                "volume_to_oi": round(vol / oi, 2), "premium_usd": round((r.bid + r.ask) / 2 * vol * r.contract.multiplier),
            })
    unusual.sort(key=lambda u: (-u["volume_to_oi"], u["contract"]))
    return {
        "call_volume": cv, "put_volume": pv, "call_open_interest": coi, "put_open_interest": poi,
        "call_put_volume_ratio": round(cv / pv, 3) if pv else None,
        "call_put_oi_ratio": round(coi / poi, 3) if poi else None,
        "unusual_count": len(unusual), "unusual": unusual[:top],
        "note": "Unusual means volume at least equal to open interest. Trade direction is unknown.",
    }


def gex(snap: MarketSnapshot, now: datetime) -> dict[str, Any]:
    """Dollar gamma exposure per 1% move in the underlying, summed over the sampled chain. Partial by construction."""
    by_strike: dict[float, float] = {}
    used = skipped = 0
    sides: dict[Any, set[Right]] = {}  # expiry -> sides that actually contributed
    spot = snap.underlying
    for r in snap.rows:
        dte = (r.contract.expiry - now.date()).days
        if r.iv is None or not r.open_interest or dte < 1:
            skipped += 1
            continue
        g = bs_gamma(spot, r.contract.strike, dte / 365, r.iv)
        if g is None:
            skipped += 1
            continue
        sign = 1.0 if r.contract.right is Right.CALL else -1.0
        by_strike[r.contract.strike] = by_strike.get(r.contract.strike, 0.0) + sign * g * r.open_interest * r.contract.multiplier * spot * spot * 0.01
        used += 1
        sides.setdefault(r.contract.expiry, set()).add(r.contract.right)
    one_sided = sorted(e.isoformat() for e, got in sides.items() if len(got) < 2)
    if not sides:
        coverage_label = "NO_ROWS_USED"
    elif one_sided:
        coverage_label = "ONE_SIDED_EXPIRIES"
    else:
        coverage_label = "BOTH_SIDES_EVERY_EXPIRY"
    cum, flip, prev = 0.0, None, None  # flip: first strike where cumulative exposure changes sign
    for strike in sorted(by_strike):
        cum += by_strike[strike]
        if prev is not None and flip is None and (prev < 0 <= cum or prev > 0 >= cum):
            flip = strike
        prev = cum
    total = cum
    return {
        "total_usd_per_1pct": round(total), "flip_strike": flip,
        "rows_used": used, "rows_skipped": skipped, "partial_chain": True,
        # The alerter refuses a net figure unless calls and puts were both sampled. We still show the number, but say
        # when it cannot be read as a net: a one-sided expiry is a sum of one sign, not an exposure balance.
        "expiries_used": len(sides), "one_sided_expiries": one_sided, "coverage_label": coverage_label,
        "net_is_interpretable": coverage_label == "BOTH_SIDES_EVERY_EXPIRY",
        "assumptions": ["Customers are long calls and short puts, so dealers hold the opposite (contested).",
                        "Open interest is the previous day's; IV is Yahoo's; the chain is a sample; no risk-free rate."],
    }


def compute_signals(snap: MarketSnapshot, now: datetime) -> dict[str, Any]:
    act = activity(snap)
    g = gex(snap, now)
    return {
        "symbol": snap.symbol, "as_of": snap.as_of.isoformat(), "coverage": coverage(snap),
        "liquidity_tiers": liquidity(snap), "activity": act, "gex": g,
        "values": {"call_put_volume_ratio": act["call_put_volume_ratio"], "call_put_oi_ratio": act["call_put_oi_ratio"],
                   "unusual_count": act["unusual_count"], "gex_total": g["total_usd_per_1pct"]},
        "status": "UNVALIDATED",
        "caveat": "Descriptive features from a delayed, sampled chain. None is validated for use in a strategy.",
    }


# ------------------------------------------------------------ does a signal predict anything?
def _ranks(xs: Sequence[float]) -> list[float]:
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    ranks = [0.0] * len(xs)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        for k in range(i, j + 1):
            ranks[order[k]] = (i + j) / 2 + 1
        i = j + 1
    return ranks


def spearman(xs: Sequence[float], ys: Sequence[float]) -> Optional[float]:
    if len(xs) != len(ys) or len(xs) < 3:
        return None
    rx, ry = _ranks(xs), _ranks(ys)
    mx, my = sum(rx) / len(rx), sum(ry) / len(ry)
    sx = math.sqrt(sum((a - mx) ** 2 for a in rx))
    sy = math.sqrt(sum((b - my) ** 2 for b in ry))
    if sx == 0 or sy == 0:
        return None
    return round(sum((a - mx) * (b - my) for a, b in zip(rx, ry)) / (sx * sy), 3)


def study_signal(store: Store, name: str, horizon_h: float = 24, limit: int = 20_000) -> dict[str, Any]:
    """Rank correlation between a signal and the underlying's forward return, from recorded real snapshots.

    Descriptive only: it never sets a signal to validated. Observations overlap, so treat the sample as
    smaller than it looks; below MIN_STUDY_SAMPLE the output says so.
    """
    if name not in SIGNAL_NAMES:
        raise KeyError(f"Unknown signal {name!r}")
    rows = store.list_snapshots(limit=limit)  # real snapshots only, oldest first
    by_symbol: dict[str, list[tuple[datetime, MarketSnapshot]]] = {}
    for r in rows:
        at = datetime.fromisoformat(r["recorded_at"])
        checked = check_snapshot(snapshot_from_dict(r["payload"]), at)
        if checked.snapshot is not None:
            by_symbol.setdefault(r["symbol"], []).append((at, checked.snapshot))
    xs: list[float] = []
    ys: list[float] = []
    skipped_gap = skipped_undefined = 0
    tol = timedelta(hours=max(1.0, horizon_h * 0.25))
    for series in by_symbol.values():
        times = [t for t, _ in series]
        for i, (t, snap) in enumerate(series):
            target = t + timedelta(hours=horizon_h)
            j = bisect.bisect_left(times, target)
            if j >= len(series):
                continue  # the future is not recorded yet
            if times[j] - target > tol:
                skipped_gap += 1
                continue
            value = compute_signals(snap, t)["values"][name]
            if value is None:
                skipped_undefined += 1
                continue
            xs.append(float(value))
            ys.append((series[j][1].underlying / snap.underlying - 1) * 100)
    n = len(xs)
    return {
        "signal": name, "horizon_hours": horizon_h, "observations": n, "skipped_gap": skipped_gap,
        "skipped_undefined": skipped_undefined,
        "spearman_rho": spearman(xs, ys),
        "mean_forward_return_pct": round(sum(ys) / n, 3) if n else None,
        "descriptive_only": n < MIN_STUDY_SAMPLE,
        "status": "UNVALIDATED",
        "caveat": ("Correlation with the underlying's next move, from overlapping observations in one market regime. "
                   "It does not validate the signal. Validation needs a pre-registered experiment and the owner's decision."),
    }


def main(argv: Optional[list[str]] = None) -> int:
    import argparse
    import json

    ap = argparse.ArgumentParser(description="Options signals from recorded snapshots (read-only)")
    ap.add_argument("--db", default="optplat.db")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("scan", help="latest signals for every recorded symbol")
    st = sub.add_parser("study", help="does a signal predict the underlying's next move?")
    st.add_argument("signal", choices=SIGNAL_NAMES)
    st.add_argument("--horizon-hours", type=float, default=24)
    args = ap.parse_args(argv)
    try:
        store = Store(args.db, read_only=True)
        if args.cmd == "scan":
            latest: dict[str, dict[str, Any]] = {}
            for r in store.list_snapshots(limit=100_000):
                latest[r["symbol"]] = r
            if not latest:
                print("No recorded snapshots found.")
                return 1
            for sym, r in sorted(latest.items()):
                at = datetime.fromisoformat(r["recorded_at"])
                print(json.dumps(compute_signals(snapshot_from_dict(r["payload"]), at), indent=2))
        else:
            print(json.dumps(study_signal(store, args.signal, args.horizon_hours), indent=2))
    except Exception as exc:  # noqa: BLE001
        print(f"Error: {type(exc).__name__}: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
