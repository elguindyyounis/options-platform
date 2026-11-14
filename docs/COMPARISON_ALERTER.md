# Comparison with options-alerter

The alerter (`elguindyyounis/options-alerter`, private, built by ChatGPT) is read-only to agents.
Based on code, not on the owner's database, which agents cannot see. Nothing here claims an edge.

## Read so far (alerter commit 1fc88f1)

* `liquidity.py`: scores volume, OI, spread and turnover into PREFERRED/WATCH/THIN tiers, flags
  orders above 10% of reported daily volume or OI, and runs `exit_stress` (extra bid concession
  scenarios). Labels itself `SCENARIO_ONLY`. The platform's sim broker fills any size at the touch
  with no such check; this run adds a label for that (`optplat/liquidity.py`).
* `agents.py`: optional local Ollama overlay. Models may only make verdicts stricter (VETO), never
  upgrade a rejection. Local-only endpoint check. Platform has no LLM layer; not needed.
* `core.py`: `finite_num`/`bounded` helpers reject NaN/inf everywhere; scores explicitly "rank
  opportunities, not likelihood of profit". Same stance as the platform's fail-closed rules.
* `storage.py`: tables for candidates, reviews, orders, positions, events, articles, earnings,
  audit, trade_journal; `is_demo` is stored on orders, positions and candidates. The platform does
  not tag demo vs real rows in its store (see CHALLENGES).

## Never read (do next)

`data_sources.py`, `server.py`, `paper_engine.py`, `risk.py`, `entry_quality.py`, `exit_decisions.py`,
`strategy_lanes.py`, `adaptive.py`, `feedback.py`, `sizing.py`, other `agent_skills/*`.
