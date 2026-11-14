# Comparison with options-alerter (read-only reference)

Alerter = the owner's other, ChatGPT-built repo. Reviewed from code only; the owner's database is not visible.

## Read so far
* `paper_engine.py`, `liquidity.py`, `risk.py`, first 80 lines of `exit_decisions.py` (2026-11-14).

## Never read yet
`agents.py`, `core.py`, `storage.py`, `server.py`, `data_sources.py`, `agent_skills/*`, `adaptive.py`,
`agent_lab.py`, `feedback.py`, `sizing.py`, `strategy_lanes.py`, `unusual_activity.py`, rest of `exit_decisions.py`.

## Findings
* **Exit friction.** Alerter's `liquidity.exit_stress` models bid concessions scaled by spread, size vs
  volume and size vs open interest, and audits them at every auto-exit. Platform sells at bid minus a
  flat 0.5% regardless of spread. Platform now has a spread-only version (`optplat/stress.py`);
  volume/OI are not available on platform quotes.
* **Honesty labels.** Alerter marks liquidity output `SCENARIO_ONLY` and states OI/volume are not live depth.
* **Shadow exits.** Model exits are shadow-only by default, fixed exits stay the comparator. Platform has no shadow-exit comparator.
* **Quote freshness.** Alerter rejects entries when held options lack reliable bid marks (`unreliable_valuation_count`); platform treats unobservable exits but does not pause entries on it (see CHALLENGES).
* **Weakness in alerter.** Hard-coded 2% / 7 agent review gating and a 30-minute stale window are far looser than the platform's 60s quote age.
