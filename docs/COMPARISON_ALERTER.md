# Comparison with options-alerter (read-only, ChatGPT-built)

Reviewed at alerter commit `1fc88f1`. First pass by the daily challenger (2026-11-13).

## What the alerter does differently

* **Entry quality gate** (`entry_quality.py`): strict real-source entry policy. Spread <=15% of ask,
  volume >=20, OI >=100, strike distance from spot by DTE horizon, 10% volume/OI participation caps,
  per-symbol/direction and basket caps (market ETFs, growth tech). The platform only has a generic
  concentration limit and spread/staleness checks; it has no volume/OI/participation checks.
* **Liquidity stress** (`liquidity.py`): scores volume/OI/spread and models exit with extra bid
  concession in BASE / THIN / STRESSED scenarios. The platform's sim exit is bid minus flat slippage.
* **Honesty plumbing** (`feedback.py`, `strategy_lanes.py`): counterfactual returns are labelled
  "indicative ask-to-bid marks, NEVER actual fills"; lane accounts refuse to show equity while any
  option is open without a quote; "no invented positions or fills". Platform marks unobservable
  positions as UNOBSERVABLE (same spirit).
* **Fail-closed risk** (`risk.py`): requires fresh quote (<30 min), sizing agent proposal, skeptic PASS;
  pauses entries if held options lack reliable bid marks.
* **Optional local LLM overlay** (`agents.py`): can only add vetoes, never upgrade a rejection.

## Read this run

`risk.py`, `liquidity.py`, `entry_quality.py`, `strategy_lanes.py`, `paper_engine.py`, parts of
`feedback.py` and `agents.py`.

## Still never read

`core.py` (beyond header), `storage.py`, `server.py`, `data_sources.py`, `adaptive.py`,
`daily_review.py`, `exit_decisions.py`, `gex.py`, `sizing.py`, `unusual_activity.py`, other
`agent_skills`.

## Where the alerter is stricter or more honest

* Liquidity participation (volume/OI) gates and exit-friction stress: platform lacks both
  (see CHALLENGES C2, C3).
* The alerter's lane ledger has no reporting of win-rate at all; the platform did print a win rate
  after one trade (fixed this run, C1).
