# Comparison with options-alerter (read-only, owner's other repo)

Started 2026-11-13. Alerter reviewed at commit `9210fd8`. Differences only; neither repo is claimed
to have an edge.

## Read so far
* `entry_quality.py`: strict entry gate for real-source options: spread <= 15% of ask, min volume
  20, min open interest 100, order <= 10% of volume/OI, 7-730 DTE, strike-distance screens by
  horizon, per-symbol/side cap of 2, basket caps for SPY/QQQ/IWM and growth tech. Poor-quality
  options are kept for research and counterfactuals but never simulated as entries.
* `feedback.py` (`mark`): shadow/counterfactual outcomes for rejected AND accepted candidates.
  Entry at ask+slippage, exit at later bid-slippage, requires a quote more than 12h after capture,
  and labels results `quote_time_verified: False`, `HYPOTHETICAL_*`, or `UNRESOLVED_NO_COMPARABLE_QUOTE`.
  Missing data becomes NO_DATA, never a guessed outcome.

## Where the alerter is stricter or more honest
* Volume/OI minimums and participation caps. The platform strategy has volume/OI minimums but the
  risk engine has no participation check (see CHALLENGES).
* Counterfactuals for rejected trades (missed vs avoided), which the platform has no equivalent of.
* Explicit "unverified quote time" and "hypothetical" labelling on every outcome.

## Where the platform is stricter
* Fail-closed state machine, idempotency keys, broker contract, kill switch, `OrderManager`
  refusing non-PAPER adapters.

## Never read yet
`agents.py`, `core.py`, `storage.py`, `server.py`, `data_sources.py`, `agent_skills/`,
`adaptive.py`, `sizing.py`, `exit_decisions.py`, `gex.py`, `strategy_lanes.py`.
