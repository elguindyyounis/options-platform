# Comparison with the alerter (`elguindyyounis/options-alerter`)

Private, built by ChatGPT, read-only for agents. Reviewed at commit `48ccf71`. Agents never copy
its code verbatim; this records ideas and honesty differences only.

## What the alerter does differently

* **Scores are labelled rankings.** `core.py` says scores "rank research opportunities, not
  calibrated likelihoods of profit"; a missing volume or quote caps the score at 34.
* **Shrinkage in learning.** `adaptive.py` weights cohort returns by `n/(n+12)` (12 neutral prior
  samples) and refuses to learn from fictional/demo candidates.
* **Hypothetical cases are labelled** `HYPOTHETICAL` (ask-to-bid value) and compared with actual
  simulated fills separately (`feedback.py`); insights wait for >= 5 samples.
* **Provenance flags on every row:** `exchange_quote_time_verified: False`, `quote_time: None`,
  `underlying_reference_basis: DAILY_HISTORY_CLOSE_NOT_INTRADAY_TAPE`, `trade_level_flow: False`.
* **AI can only tighten.** `agents.py` lets an optional local model add a VETO but never upgrade a
  rejection; remote model endpoints are refused; headlines are treated as untrusted.
* **Unusual volume/OI is evidence, not intent:** reports say opening buys / aggressor cannot be
  established.
* **Thin-contract caps** (volume < 5, OI < 20, spread > 20% limit the score).

## Modules read so far

`core.py` (partly), `agents.py` (partly), `data_sources.py` (first 60 lines), `adaptive.py` and
`feedback.py` (grep only), `strategy_performance.py` (grep only).

## Never read yet

`storage.py`, `server.py`, most of `data_sources.py`, `lane_paper_engine.py`,
`shadow_lane_runner.py`, `agent_skills/*` (only `skeptic-red-team` listed), `exit_decisions.py`,
`entry_quality.py`, `liquidity.py`, `trade_confluence.py`.

## Where the platform is already stricter

Fail-closed risk engine, state-machine orders, token auth, conservative simulated fills
(buy at ask + slippage, sell at bid - slippage).

## Where the alerter is stricter or more honest (platform gaps)

* Win rate shown with no sample-size label (fixed on `agent/2026-11-14-lane-sample-honesty`).
* No shrinkage or minimum-sample rule anywhere in the platform report.
* Quotes carry no verified-time provenance in reports (see CHALLENGES #3).
