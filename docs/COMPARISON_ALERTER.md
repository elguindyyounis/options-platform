# Comparison with options-alerter

Source: the owner's private, read-only repo `options-alerter` (built with ChatGPT), read at commit
`1fc88f1`. This file records what was actually read, so later runs do not guess.

## Read so far

* `README.md`, `feedback.py`, `adaptive.py`, `agents.py`, `core.py` (first 120 lines).

## Never read yet (read one per run)

`storage.py`, `server.py`, `data_sources.py`, `agent_lab.py`, `sizing.py`, `exit_decisions.py`,
`entry_quality.py`, `liquidity.py`, `risk.py`, `gex.py`, `unusual_activity.py`, `intraday_strategy.py`,
`strategy_lanes.py`, `daily_review.py`, `research_foundations.py`, `agent_skills/*`, rest of `core.py`.

## What the alerter does that the platform does not

* **Shadow (counterfactual) cases** (`feedback.py`). Every scan samples contracts, including ones that
  were rejected or not selected, and re-marks them at 1, 7 and 30 days. This measures whether the
  vetoes were right. The platform records no rejected candidates at all.
  Honest details worth copying: slippage on both legs, a quote only counts if it is >12h after
  capture, unresolved cases stay `NO_DATA` instead of being given a return, labels say
  `HYPOTHETICAL_*`, and a cohort needs >=5 samples before any sentence is printed.
* **Cohort calibration** (`adaptive.py`). Ranking is nudged by closed-trade cohorts, but only with
  >=5 real trades, >=3 per cohort, shrinkage toward neutral (12 pseudo-samples), per-trade return
  capped to +/-100%, total adjustment capped at +/-7 points. The platform has no learning step.
* **Demo/real separation** is enforced in code paths (`is_demo`, `data_source == 'yfinance'`), not
  only in labels.
* A seven-role "council" with a deterministic skeptic gate. This is mostly narrative around a
  score; the binding limits are the deterministic ones.

## Where the platform is stricter or the alerter is weaker

* Alerter paper exits run only when a scan happens to refresh the held contract (up to 30 min stale).
  The platform requires a quote no older than 60s or reports UNOBSERVABLE.
* Alerter treats unofficial yfinance quotes as usable with `quote_time_verified: False` stamped on.
  The platform fails closed unless the owner opts in.
* Alerter cohort win/loss counts (`feedback.summary`) show counts with no interval at 5 samples.

## Where the alerter is more honest

* Its summary text refuses to infer ("do not assume the original veto was mistaken") and keeps
  missing quotes unresolved. The platform's `/api/report` printed a win rate from n=1 before this
  run (fixed in the branch `agent/2026-11-14-result-evidence`).
