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

`storage.py` (head, run 2): `trade_journal` keeps `exit_quote_at` and `exit_reason` per closed trade, and the
default store settings are big (8% per position, 40% total, 30% drawdown, take-profit 40 / stop 30). These
are the owner's experimental values and are not copied or changed here.

`lane_paper_engine.monitor_lane_options` (run 3): an exit can only fire on a bid quote newer than the entry
quote and newer than the last saved mark (replayed marks cannot advance a trailing peak); a held contract
missing from the snapshot is marked UNOBSERVABLE, never given a fabricated exit; exit quotes with spread above
`MAX_EXIT_SPREAD_PCT` (20%) are treated as unobservable (so a wide-spread stop does not fire, which can delay a
loss exit; the platform instead exits on any valid bid). The alerter explicitly does not assume a stop fills at
the trigger level; it fills at the observed bid less slippage, same idea the platform's `fill_vs_trigger_bid`
now reports.

`agents.py` (run 4): the council is deterministic first; the optional local Ollama step only accepts
localhost endpoints, treats headlines as untrusted, and can only add caution (a VETO), never upgrade a
rejection. `run_council` keeps rejected trades rejected and logs the real agent sequence, not invented
dialogue. `data_sources.option_rows`: Yahoo rows carry `quote_time: None`,
`exchange_quote_time_verified: False`, `last_trade_at` (lastTradeDate), and zero-volume rows are dropped unless
pinned. The platform's Yahoo provider is equally unverified (pinned by tests) but ignores last-trade time (C8).

## Never read yet (next runs)

`storage.py`, `server.py`, rest of `storage.py`, rest of `core.py` and `data_sources.py`,
`lane_paper_engine.py` exit logic (trailing stop, `MAX_EXIT_SPREAD_PCT`), `sizing.py`, `risk.py`,
`adaptive.py`, `feedback.py`, other `agent_skills`.

## Open question for the owner

Both systems model fills from Yahoo-style quotes whose time is the download time. Neither can show
realised execution quality. Only recorded quotes plus a real paper broker will (BACKLOG items 1-3).
