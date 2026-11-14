# Comparison with options-alerter (read-only reference)

Alerter reviewed at commit `1fc88f18f2875bb115f8264700a9835cebe45c80`. Written from code only; I cannot see
the owner's database, so nothing here says how either system performs.

## Modules read so far
* `liquidity.py` (2026-11-14): liquidity tiers (PREFERRED/WATCH/THIN) from volume, OI, spread; flags when the
  order size exceeds 10% of reported daily volume or OI; `exit_stress` models bid liquidation with extra
  concession (BASE_BID, THIN_MARKET, STRESSED_EXIT). Labelled `SCENARIO_ONLY` throughout.
* `agents.py` (2026-11-14): optional local Ollama overlay. Model output may only make a verdict MORE
  cautious (a VETO can override a pass; nothing can upgrade a rejection). Only localhost endpoints are
  allowed, headlines are marked untrusted. A good pattern: an LLM may tighten, never authorize.
* `core.py` (2026-11-14, first 80 lines): score is documented as a ranking, "not a calibrated likelihood";
  Black-Scholes greeks are labelled as assumed-input approximations.
* `exits.py` equivalent is `exit_decisions.py` (not yet read).

## Never read yet
`storage.py`, `server.py`, `data_sources.py`, `sizing.py`, `feedback.py`, `adaptive.py`, `strategy_lanes.py`,
`intraday_strategy.py`, `risk.py`, `agent_skills/`, rest of `core.py`.

## Where the alerter is stricter or more honest than the platform
1. Order size vs reported volume/OI is checked (`liquidity_assessment`). The platform's sim fill is ask +
   0.5% regardless of size, so large quantities in thin contracts look better than reality.
2. Exit friction is stress-tested in scenarios; the platform marks open positions at bid only.
3. Every output carries an explicit `status`/`limits` string saying what it is not.

## Where the platform is stricter
Fail-closed quote validity and verified quote time, an order state machine with reconcile, and a hard
refusal of non-PAPER adapters.
