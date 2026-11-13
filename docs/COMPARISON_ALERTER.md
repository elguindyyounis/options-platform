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

## Where the alerter is stricter or more honest
* Exit fills are stress-tested; the platform's SimBroker uses a flat 0.5% slippage regardless of
  spread or size. Addressed in `src/optplat/stress.py` (not yet wired into reports).
* Counterfactual/missed-trade journal with fixed horizons. The platform has nothing like it.

## Never read yet
`agents.py`, `core.py`, `storage.py`, `server.py`, `data_sources.py`, `agent_skills/`, rest of
`feedback.py`, `adaptive.py`, `sizing.py`, `risk.py`.
