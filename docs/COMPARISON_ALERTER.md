# Comparison with the alerter (elguindyyounis/options-alerter)

The alerter is the owner's other, ChatGPT-built, private repo (read-only to agents). This file records
what was read and what was learned. Alerter modules are Python scripts with very dense style.

## Read so far
* `liquidity.py`, `entry_quality.py`, `paper_engine.py`, `core.py` (first 225 lines), `exits` caller.
* Reviewed up to alerter commit `9210fd8`.

## Never read yet (read one per run)
`agents.py`, `storage.py`, `server.py`, `data_sources.py`, `adaptive.py`, `feedback.py`,
`exit_decisions.py`, `sizing.py`, `strategy_lanes.py`, `intraday_strategy.py`, `daily_review.py`,
`agent_lab.py`, `research_foundations.py`, `gex.py`, `unusual_activity.py`, `agent_skills/*`.

## Where the alerter is stricter or more honest than the platform
* **Participation gates.** `entry_quality.py` rejects orders above 10% of reported daily volume or
  open interest. The platform's size cap is dollar-based only, so a large paper order in a thin
  contract fills at the limit with no depth consideration. (This run: platform now *displays* it.)
* **Exit stress.** `liquidity.exit_stress` models bid liquidation with extra concession by spread and
  participation. The platform's sim broker fills at the limit with no concession.
* **Zero bid is not observable.** Alerter refuses entries where bid is 0. Platform strategy requires
  `bid > 0` already, so this matches.
* **Honesty labels everywhere.** Alerter outputs carry `SCENARIO_ONLY` / "not a probability" notes.
  The platform does this in docstrings but not on its API payloads (the new review adds `limits`).
* **Concentration baskets** (SPY/QQQ/IWM, growth tech) are hand-coded heuristics. Platform has only a
  same-underlying/direction limit. Needs an owner decision (risk policy), so not copied.

## Where the platform is stricter
* Fail-closed risk engine, order state machine with reconcile, idempotency keys, kill switch,
  `OrderManager` refusing non-PAPER adapters, token auth. The alerter's gates are in scripts.
