# Comparison with options-alerter

Read-only comparison with the owner's private repo `options-alerter` (commit `9210fd8a16b10fb622790cc7dd82980c74a6af08`). First run: the
earlier comparison was not in this repo, so this file starts fresh and records only what was read.

## Read so far
* `paper_engine.py`: exit manager. A failed quote fetch is recorded as UNOBSERVABLE monitoring
  failure, never a HOLD (the platform's `exits.py` already does the same). Every exit also records a
  liquidity stress scenario in the audit log.
* `liquidity.py`: `exit_stress` re-prices liquidation with extra bid concession from spread,
  contracts vs daily volume, contracts vs open interest. Labelled "scenario only, not a fill".
* `feedback.py` (first 120 lines): rejected/missed setups get counterfactual returns at 1/7/30 days,
  explicitly labelled "indicative ask-to-bid marks, NEVER actual fills".

* `sizing.py`: sizing is an "ordinal evidence index, NOT a win probability"; caps evidence at 0.78
  and fraction at 0.60 until enough closed trades; shrinks size at 10%/20% drawdown; `goal_affects_size`
  is hard-coded False (falling behind a goal never raises risk). Real-source entries also capped by
  daily-volume and open-interest participation.
* `adaptive.py`: cohort-shrunken ranking nudge, capped at +/-7 points, inactive below 5 real closed
  trades; demo outcomes never train real calibration. Weakness to note: a cohort needs only 3 trades
  to contribute, win rates carry no interval, and every closed trade counts equally regardless of
  lane, so many cohorts judged on few trades can look informative by chance. Descriptive text is
  labelled "selection-biased; not a forecast".

## Where the alerter is stricter or more honest
* Exit fills are stress-tested; the platform's SimBroker uses a flat 0.5% slippage regardless of
  spread or size. Addressed in `src/optplat/stress.py` (not yet wired into reports).
* Counterfactual/missed-trade journal with fixed horizons. Now mirrored in `src/optplat/counterfactual.py`
  (not yet wired into the engine), stricter in three ways: a later quote must be 12h+ after the
  decision, unresolved cases are counted in every summary, and means are withheld below 30 resolved.

## Read on 2026-11-13 (third pass)
* `risk.py` (alerter): deterministic gate. Stale check uses the *fetch* time (30 min), and a missing
  exchange quote time is only a warning, so a delayed yfinance chain can pass. Spread cap is 35% of
  ask, sizing/caps are percent-of-equity. The platform is stricter on all of these (60s age, 15%
  spread, verified quote time required by default). Do not copy the alerter's looser gates.
* `agents.py` (alerter): optional local Ollama overlay can only make a verdict more cautious
  (VETO, never PASS), endpoint restricted to localhost, headlines marked untrusted. A good pattern
  if the platform ever adds a model reviewer: tighten-only, local-only.
* `data_sources.py` (partial): yfinance rows carry `quote_time=None` and `exchange_quote_time_verified=False`,
  so alerter "freshness" really means "when we downloaded it". Same caveat applies to any platform
  run on the free Yahoo provider.

## Never read yet
`core.py`, `storage.py`, `server.py`, `agent_skills/`, rest of `data_sources.py` and `feedback.py`.
