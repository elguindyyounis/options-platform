# Platform vs. options-alerter (read-only comparison)

Alerter commit reviewed: `48ccf71` (v2.8.0-decision-first). The alerter is the owner's other,
ChatGPT-built, private repo. This is a code read only: the owner's database is not visible from
here, so nothing below says how either system has actually performed.

## Shape

| | options-platform | options-alerter |
|---|---|---|
| Size | ~2.2k lines, 11 modules | ~8.5k lines, ~40 modules |
| Core idea | Broker-ready, fail-closed order pipeline; one baseline strategy | Research lab: multi-agent "council", many isolated strategy lanes, journals |
| Fills | SimBroker: ask + slippage, limit must cover | Modeled ask+friction buy, bid-friction sell, per-lane isolated ledgers |
| Marks | Report per row is honest (`UNOBSERVABLE`); headline equity is not (see CHALLENGES C1) | Equity is `None` if any open mark is stale or missing (`lane_portfolio`) |
| Quote freshness | `max_quote_age_s=60`, verified timestamp required | 1800 s max age; download time explicitly not an exchange time |

## Where the alerter is stricter or more honest

* `lane_portfolio` refuses to give an equity estimate when any open mark is stale; the platform's
  `SimBroker.get_account` marks an unquotable position at cost. (Addressed in the 2026-11-15 run.)
* `liquidity.py` carries a `SCENARIO_ONLY` status and an `exit_stress` model (bid concession scaled by
  spread, participation and OI concentration). The platform has no exit-friction stress at all.
* `strategy_performance.py` labels closed-trade drawdown as NOT account drawdown, returns null (not 0%)
  for win rate with no trades, and refuses to name a "winner" against imported competitor trades.
* Adaptive ranking only shifts after 5+ completed real-source trades and is bounded (+-7). The skill
  docs require a forward held-out comparison before calling a change more profitable.
* Demo and real-source results are kept strictly separate in the learning data.

## Where the platform is stricter

* One deterministic, fail-closed risk engine; `OrderManager` refuses non-PAPER adapters.
* Idempotent orders, state machine with reconcile, broker conformance suite.
* Token + host checks on the API.
* Alerter lane sizing is large and experimental (5% risk per idea, 15% total premium in the aggressive
  lane); that is the owner's decision and is not touched here.

## Modules read so far

`liquidity.py`, `strategy_performance.py`, `lane_paper_engine.py` (first 140 lines: policy table, quote
validity, `lane_portfolio`), `core.py` (head), `data_sources.py` (head), `agent_skills/skeptic-red-team`,
`CHANGELOG.md`.

## Never read yet (next runs)

`agents.py` (council, Ollama call), `storage.py`, `server.py`, rest of `core.py` and `data_sources.py`,
`lane_paper_engine.py` exit logic (trailing stop, `MAX_EXIT_SPREAD_PCT`), `sizing.py`, `risk.py`,
`adaptive.py`, `feedback.py`, other `agent_skills`.

## Open question for the owner

Both systems model fills from Yahoo-style quotes whose time is the download time. Neither can show
realised execution quality. Only recorded quotes plus a real paper broker will (BACKLOG items 1-3).
