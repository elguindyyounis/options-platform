"""Signal provenance: every signal or label this platform shows, where it came from and how much it has been tested.

Display-only. Nothing here changes what a lane trades. The point is honesty: most of what the dashboard calls a signal is a
developer heuristic computed from free, delayed data, and none has been shown to predict returns. Idea taken from the
owner's options-alerter repo (``research_foundations.py``), rewritten here.

``validation`` is UNVALIDATED for every entry. It may only become VALIDATED for a name the owner has added to
``signals.VALIDATED_SIGNALS`` (a test keeps the two in step), so this table cannot quietly promote a signal.
"""
from __future__ import annotations

from typing import Any

from .signals import SIGNAL_NAMES, VALIDATED_SIGNALS

# origin: HEURISTIC = chosen by a developer, STANDARD_MODEL = textbook formula with stated assumptions,
#         INFERENCE = a guess about something the feed does not report (who traded, open or close)
PROVENANCE: tuple[dict[str, Any], ...] = (
    {"id": "volume_vs_open_interest", "where": "scanner.unusual_contracts", "origin": "HEURISTIC",
     "definition": "Day's volume at or above 100 contracts and at least the set ratio of the previous day's open interest.",
     "caveat": "Open interest updates once a day, so intraday volume against it overstates how unusual a print is. The thresholds were not fitted to anything."},
    {"id": "likely_side", "where": "scanner.trade_side", "origin": "INFERENCE",
     "definition": "BUY if the last print was at or above the ask, SELL if at or below the bid, otherwise unclear.",
     "caveat": "One delayed last print stands for a whole day's volume, and the feed does not say who initiated it. A hint, not a fact."},
    {"id": "open_or_close", "where": "scanner.compare_with_prior", "origin": "INFERENCE",
     "definition": "Next-day open interest rising or falling against the earlier sighting's volume.",
     "caveat": "Open interest nets everything that day; it cannot separate this trade from others."},
    {"id": "flow_lean", "where": "scanner.sentiment", "origin": "HEURISTIC",
     "definition": "Dollar-weighted bullish versus bearish unusual contracts, counting only inferred buys and sells.",
     "caveat": "Built on the likely_side inference, so it inherits that weakness; a covered call or a hedge reads the wrong way."},
    {"id": "sightings", "where": "scanner.annotate_with_history", "origin": "HEURISTIC",
     "definition": "How many separate days the same contract was unusual.",
     "caveat": "Persistence is assumed to matter. No study has checked it."},
    {"id": "liquidity_tier", "where": "liquidity.liquidity_tier", "origin": "HEURISTIC",
     "definition": "PREFERRED / WATCH / THIN from volume, open interest and spread; anything missing is THIN.",
     "caveat": "Open interest and volume are not an order book. Cut-offs were chosen by a developer."},
    {"id": "stressed_exit", "where": "liquidity.stress_exit", "origin": "HEURISTIC",
     "definition": "Bid minus a concession that grows with spread and with size against volume and open interest.",
     "caveat": "A pessimistic what-if, not a price anyone could have traded at. The coefficients are guesses."},
    {"id": "ema9_vwap_cross", "where": "shortterm", "origin": "HEURISTIC",
     "definition": "Intraday EMA9 / VWAP rule on 5-minute bars of the underlying.",
     "caveat": "Delayed data; the settings were fixed before results but not derived from evidence."},
    {"id": "daily_pullback", "where": "swing", "origin": "HEURISTIC",
     "definition": "Pullback inside an uptrend on daily bars (SMA and RSI).",
     "caveat": "Backward-looking price rule. Replays on a short history say little."},
    {"id": "black_scholes_gamma", "where": "signals.bs_gamma", "origin": "STANDARD_MODEL",
     "definition": "Black-Scholes gamma with a zero rate and the chain's quoted implied volatility.",
     "caveat": "European-style model on American options; implied volatility from a delayed quote."},
    {"id": "call_put_volume_ratio", "where": "signals.compute_signals", "origin": "HEURISTIC",
     "definition": "Call volume over put volume across the sampled chain.", "caveat": "The chain is a sample, not every strike and expiry."},
    {"id": "call_put_oi_ratio", "where": "signals.compute_signals", "origin": "HEURISTIC",
     "definition": "Call open interest over put open interest across the sampled chain.", "caveat": "Same sampling limit as the volume ratio."},
    {"id": "unusual_count", "where": "signals.compute_signals", "origin": "HEURISTIC",
     "definition": "Number of contracts passing the unusual-activity test in the sampled chain.", "caveat": "Inherits every limit of volume_vs_open_interest."},
    {"id": "gex_total", "where": "signals.gex", "origin": "STANDARD_MODEL",
     "definition": "Modeled net gamma exposure, assuming customers are long calls and short puts.",
     "caveat": "That dealer-positioning assumption is contested, and the sampled chain makes the sum partial."},
)


def provenance() -> dict[str, Any]:
    rows = []
    for p in PROVENANCE:
        validated = p["id"] in VALIDATED_SIGNALS
        rows.append({**p, "validation": "VALIDATED" if validated else "UNVALIDATED"})
    return {
        "signals": rows,
        "unvalidated": sum(1 for r in rows if r["validation"] == "UNVALIDATED"),
        "note": "None of these has been shown to predict returns. UNVALIDATED means no pre-registered study has supported it yet. "
                "Listed signals marked INFERENCE are guesses about facts the free data does not report.",
        "covers_signal_names": list(SIGNAL_NAMES),
    }
