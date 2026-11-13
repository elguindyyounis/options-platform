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

## Never read yet
`agents.py`, `core.py`, `storage.py`, `server.py`, `data_sources.py`, `agent_skills/`, rest of
`feedback.py`, `risk.py`.
