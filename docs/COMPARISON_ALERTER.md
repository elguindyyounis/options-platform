# Comparison: options-platform and options-alerter

Written 2026-11-12 against alerter commit `9210fd8`. The alerter is the ChatGPT-built private repo; this platform is the
Claude-built one. This is a code-reading comparison, not a performance comparison: neither project has produced evidence
of a trading edge, and nothing here should be read as saying one earns more than the other.

**What was read:** the alerter's README, `PRODUCT_DECISION_ARCHITECTURE.md`, `CHANGELOG.md`, `RELIABILITY_AUDIT.md`,
`gex.py`, `unusual_activity.py`, `entry_quality.py`, `liquidity.py`, `risk.py`, `sizing.py`, `strategy_lanes.py`,
`intraday_strategy.py`, `exit_decisions.py`, `feedback.py`, `adaptive.py`, `agent_lab.py`, `research_foundations.py`,
`daily_review.py`, two agent skill files and the CI workflow. **Not read at the first pass (`agents.py` and `core.py` read 2026-11-13, see the end of this file):** `storage.py`,
`server.py`, `data_sources.py`, the other skill files, and its tests (none were run). Claims about those are not made.

## Side by side

| Area | options-alerter | options-platform | Who looks stronger, and why |
| --- | --- | --- | --- |
| Unusual option activity | Volume and OI thresholds, no aggressor, no open/close inference, no history | Same thresholds plus buy/sell inference from the last print against bid/ask, open/close inference from OI changes, a persistence history table, follow-up reads | Platform: it adds three kinds of evidence. All of it is still inference from delayed free data. |
| Universe and breadth | Per-symbol scans; no market-wide heat map found | 200 names in 19 sectors, heat map, sentiment, sector caps | Platform |
| Modeled gamma exposure (GEX) | Black-Scholes gamma, 0 to 45 DTE, refuses truncated or biased chains, dealer-sign convention stated as an assumption | None | Alerter. Port candidate (backlog). |
| Entry quality gates | Strict: spread ≤15% of ask, volume ≥20, OI ≥100, size ≤10% of volume and OI, per-symbol and basket caps | Per-lane spread and OI limits; size recorded against volume and OI and tagged afterwards, not gated | Alerter is stricter. The platform's lanes are deliberately looser (owner asked for experiments), but they tag what the alerter would block. |
| Liquidity tiers and exit stress | PREFERRED/WATCH/THIN, plus an extra exit concession for wide spreads and large size | Now ported (`liquidity.py`): tier and stressed exit in every post-mortem, plus an `EXIT_STRESS_FLIPS_RESULT` tag | Equal after this change |
| Simulated trading that actually runs | Four lanes; three are shadow standby or data blocked with automatic orders off. The intraday study is a 3-minute stock proxy, not option P&L. Its own audit (2026-11-10) found 12 positions open and none closed | Five option lanes with automatic simulated entries and exits, fees, stops, targets, stacking | Platform runs more experiments. Whether any is profitable is unknown. |
| Post-mortems on losses | Decision-feedback journal with drivers; a daily review | Rule-based tags per closed trade, a digest, and a minimum of 5 trades before a cause counts as a pattern | Roughly equal; different shape |
| Counterfactuals (rejected and unselected contracts) | Yes: samples scored, rejected and unselected contracts and checks 1, 7 and 30 days later at ask in, bid out | None. Only taken trades are reviewed. | Alerter. Highest-value gap (backlog item 1). |
| Learning from outcomes | Cohort calibration, capped at ±7 score points, off below 5 real trades, shrunk toward neutral, never trained on demo data | Digest only; nothing feeds back automatically | Alerter has a bounded feedback loop. Risk: a few trades can steer it, so keep the cap and the minimum. |
| Exit research | Deterministic shadow exits, optional local model, hard stop/target/hold always win | Fixed premium stop/target/time rules per lane | Alerter explores more. Its shadow exits are hypotheses; none validated. |
| Safety posture | Fail-closed risk engine, skeptic/CIO veto, atomic admission, refuses to buy without exits | Fail-closed `RiskPolicy`, order state machine, `OrderManager` refuses non-paper adapters; research lanes have no order path (AST-tested) | Both strong. Different designs. |
| Research honesty | `research_foundations.py` records the source and validation status of each signal, cites overfitting papers | Limitations strings per lane, "paper proves nothing" throughout | Alerter documents signal provenance better. Port candidate (docs). |
| Operations | launchd deployment with rollback, reliability audit, CI that runs a stock-proxy replay | CI on tests; run script | Alerter |
| Remote and always-on | Mac only; says an offline Mac cannot report its own outage | Same limitation | Equal |

## Where the platform may be wrong

These are challenges raised by reading the alerter. None is proven.

1. **Paper exits were too friendly.** Lanes sold at the bid with no allowance for size. The alerter charges extra when
   the spread is wide or the size is large. With stacking and bigger sizes, this matters more here. *Addressed in this change
   for the post-mortem view; the lane P&L itself still uses the bid, so headline results remain optimistic.*
2. **Unusual-activity signals have no scoreboard.** The platform labels contracts but never checks later whether the
   labelled ones did better than the unlabelled. The alerter's counterfactual journal is the pattern to copy.
3. **Many lanes means many chances to look good by luck.** Five lanes with different settings, judged on small samples,
   is the multiple-comparisons trap the alerter cites. The digest's 5-trade minimum is a floor, not a defence.
4. **No frozen baseline.** Lanes are compared with each other, not with a rule that never changes.
5. **Buy/sell and open/close labels are inferred** from one delayed print and a daily OI number. Treat them as hints.

## Ported in this change

* `src/optplat/liquidity.py`: tier and stressed-exit functions (fail-closed: missing data is THIN and costs the maximum).
* Post-mortems now carry `liquidity_tier`, `stress_net_pct`, `stress_concession_pct` and the `EXIT_STRESS_FLIPS_RESULT` tag.
* No risk limit, lane size or default was changed. Tests: `tests/test_liquidity.py`.

## Not ported, and why

* **Net GEX.** Needs gamma per contract and a dealer-positioning convention that is an assumption. Worth doing as a
  display-only research field, in its own change.
* **Counterfactual journal.** Needs a new table and a daily job that revisits contracts; too large for this change.
* **Cohort calibration.** Would change which trades lanes take. Wait until there are enough closed trades to calibrate on.
* **Strict entry gates.** Applying them would shrink the experiments the owner asked for. The post-mortem tags show what
  they would have caught.
* **Anything about the alerter's council, sizing or goal tracker.** Not read closely enough to judge.

## Addendum 2026-11-13: `agents.py` and `core.py` (alerter still at `9210fd8`; nothing new to review)

* **Optional local model can only be stricter.** `agents.py` lets a local Ollama model add risks and raise a VETO in the Skeptic
  role, but never pass or upgrade a deterministic rejection; if the Skeptic vetoes, the CIO verdict is forced to REJECT. It also
  refuses any non-localhost endpoint so trading data is not sent out. The platform's committee has no model in it, so there is
  nothing to port, but the "may only tighten" rule is the same shape as the platform's flow agent.
* **Hard veto list is tighter than the platform's lanes by design.** `core.research_case` vetoes: under 7 days to expiry, missing or
  crossed quote, spread over 35%, zero volume, unknown data source. The platform's aggressive lanes deliberately trade closer to
  expiry and thinner contracts (owner's choice); the post-mortem tags show what these gates would have caught. No change made.
* **Scores are labelled as rankings.** `core.py` states agent scores "rank research opportunities, not calibrated likelihoods", and
  the sizing agent is told never to turn an evidence index into a win probability. The platform's Research page does the same with
  its "too few" labels; worth keeping that wording in any future scoring.
* **Thin contracts are capped, not just penalised.** `candidate_score` caps the score at 52 below 5 volume, 55 below 20 open
  interest and 56 above 20% spread, so a tiny denominator cannot rank high on volume/OI ratio. The platform's tracker groups flagged
  contracts by what was known at the flag, but does not yet show whether the ratio is dominated by tiny open interest.
  Logged as challenge 7.
* **Still not read:** `storage.py`, `server.py`, `data_sources.py`, other skill files, the alerter's tests.

## Addendum 2026-11-13 (later): `storage.py` and `data_sources.py` (alerter still at `9210fd8`)

* **Paper buys re-check everything inside one transaction.** `paper_buy_atomic` re-reads the candidate, rejects a changed quote,
  a stale real-source quote (older than 30 min or more than 2 min in the future), a duplicate idempotency key, an open position
  on the same contract, the kill switch, and re-runs entry quality, so a competing scan cannot slip an order past a limit.
* **Limits use the more conservative equity.** For real-source quotes the drawdown and exposure checks use cash plus the lower of
  cost and the bid mark of open holdings, and entries pause if any held contract has a stale, crossed or over-35% spread quote.
  The platform's lanes mark open positions for display; whether any limit uses a pessimistic mark was not checked here.
* **Fills are ask plus slippage** (default 0.5%, capped 3%), validated against the saved quote.
* **Data honesty.** `data_sources.py` states that download time is not market time and tags activity rows
  `opening_trade_verified: False` and `trade_aggressor_verified: False`. The platform's inferred side and open/close labels are
  the same kind of guess and are labelled as inferences.
* **Refuses biased GEX.** Over the row cap, or with missing call/put sides, the scan declines to publish a partial net exposure.
* **Still not read:** `server.py`, other skill files, the alerter's tests.

## Addendum 2026-11-14 (later): alerter moved `9210fd8` -> `48ccf71`

* **Manual GEX refresh now refuses one-sided chains (#16).** `gex.py` raises unless both calls and puts have at least one usable
  positive-OI, finite-IV row per expiry, and refuses over the row cap. The platform's `signals.gex` kept publishing a net figure
  from a calls-only or puts-only sample. Challenge 8: now flagged with `two_sided` / `sides_used` (display only; figures unchanged).
* **Holdout discipline in the intraday research (#29).** `intraday_reel_study.study` splits days 70/30 in time, fits only on the
  earlier days, ranks with a drawdown-penalised score (explicitly "NOT p-values"), and replays the later days for the chosen rule
  against a frozen raw baseline. Output warns that the Instagram claims are unverified and that train-only choices are never promoted.
  This is the standard the platform's strategy evaluation should keep (time-ordered split, frozen baseline, minimum trade counts).
* **GEX confluence policy (`GEX_CONFLUENCE_POLICY.md`).** Walls are "largest modeled concentration", not support or resistance;
  GEX is used only if the scan is under 90 minutes old, covers the near expiries, has usable call AND put gamma, and agrees with
  spot within 2%. The platform has no spot-disagreement or freshness gate on its GEX display; logged as challenge 9 (owner decision
  on thresholds is not needed for a display flag, but not done this run).
* **Run challenger-n (alerter still `48ccf71`):** the alerter checks GEX spot against an independent reference spot; the platform
  snapshot has only its own spot, so the display flag cross-checks it with put-call parity instead. This is weaker than the alerter's
  check and says so. Still not read: `server.py`, `sector_rotation.py`, `technical_confluence.py`, `goal_sprint.py`, its tests.
* **Read this run:** the diffs of `gex.py`, `intraday_strategy.py`, `intraday_reel_study.study`, and `GEX_CONFLUENCE_POLICY.md`.
  Not read in depth: `sector_rotation.py`, `technical_confluence.py`, `goal_sprint.py`, `server.py`, the alerter's tests (not run).

## Addendum 2026-11-15: `strategy_performance.py` (read)

* Per-lane stats come only from closed positions. Win rate, average and equity are null, never 0, when there is nothing to
  compute them from; open-option equity is null if any mark is missing or stale (`equity_observable`).
* Its drawdown is named `closed_trade_only_max_drawdown_pct` with a note that it excludes unrealized declines and is not
  account drawdown. Every journal row carries `modeled_not_broker_fills`; the report says quote timestamps are unverified.
* The competitor comparison refuses to name a winner (`winner: None`), requires dated trades, and only pairs unique
  contract/entry-day matches. Same stance as this platform's no-edge rule; no change needed there.
* Platform gap found: nothing showed a result without its best trade (challenge 10, done) and the equity-chart drawdown is not
  labelled as sampled (challenge 11, open). Still not read: `server.py`, `sector_rotation.py`, `technical_confluence.py`, `goal_sprint.py`, tests.

## Addendum 2026-11-15 (challenger-b): `server.py` (alerter still `48ccf71`)

* **Public bind needs a token.** Refuses to start on a non-loopback host unless `OA_ADMIN_TOKEN` is at least 24 characters. Host header must be
  loopback (DNS-rebinding guard) when no token is set. POSTs must be same-origin JSON, reject `Sec-Fetch-Site: cross-site`, and cap bodies at 16 KB.
  The platform's `api.py` has token and host checks; whether it also rejects cross-origin and non-JSON POSTs was not compared here. Auth
  changes may only be tightened and need the owner, so this is logged, not changed.
* **`automation_readiness` is honest about what it cannot know.** Status is `CONFIGURED_NOT_LIVE_VERIFIED` at best, `quote_time_verified: False`,
  and it blocks automatic entries when held contracts have stale, missing or over-35% spread marks, or the exit monitor heartbeat is stale.
  The platform's runner health shows heartbeat; it has no "held marks unobservable" blocker. Candidate for a later challenge.
* **Still not read:** other skill files, `sector_rotation.py`, `technical_confluence.py`, `goal_sprint.py`, the alerter's tests (not run).

## Addendum 2026-11-15 (challenger-c): `entry_quality.py` (alerter still `48ccf71`)

* **Entry gates the alerter applies to real-source paper entries:** spread at most 15% of ask, a nonzero bid, volume at least 20, open interest
  at least 100, order size at most 10% of reported daily volume and 10% of open interest, 7 to 730 days, strike within 30/40/60% of spot by
  horizon, at most two open contracts per symbol and side, and basket caps (SPY/QQQ/IWM three, big growth tech four). Its docstring says
  "Observation is not authorization": poor-quality contracts stay in research but are never simulated as entries.
* **Platform difference:** the lanes buy at the ask with large experimental budgets (owner's choice, not changed). Size against volume and OI was
  recorded and tagged `OVERSIZED_FOR_LIQUIDITY` per trade, but no summary said how much of a lane's realized P&L came from oversized fills
  (challenge 12, done). Basket caps and the strike-distance screen have no platform equivalent; they are entry rules, so they stay an owner decision.
* **Still not read:** other skill files, `sector_rotation.py`, `technical_confluence.py`, `goal_sprint.py`, the alerter's tests (not run).

## Addendum 2026-11-15 (challenger-d): `sizing.py` and `risk.py` (alerter still `48ccf71`)

* **Sizing shrinks with thin evidence.** Its evidence index is capped at 0.78 below 20 comparable closed outcomes, and the size fraction is capped
  (0.60, or 0.45 for the balanced profile) below 10. It labels the index "NOT win probability" and `calibrated_probability` is `None`. Goals never raise
  size (`goal_affects_size: False`). The platform's committee scale learns from outcomes; whether it also shrinks on few samples was not compared here.
  Sizing and lane budgets are owner decisions, so this is logged, not changed.
* **Risk gate is fail-closed and layered:** kill switch, all seven reviews matching the current quote snapshot, spread at most 35%, quote fetch under 30
  minutes old, per-position, per-symbol and total premium caps, drawdown stop, and new entries paused when held options have no reliable bid mark. The last
  one is the same gap noted for `automation_readiness` (platform has no "held marks unobservable" blocker).
* Platform gap found: results were never split by underlying or day (challenge 13, done).
* **Still not read:** other skill files, `sector_rotation.py`, `technical_confluence.py`, `goal_sprint.py`, the alerter's tests (not run).

## Addendum 2026-11-15 (challenger-e): `goal_sprint.py` (read)

* A goal is arithmetic, never risk authority: `goal_alters_position_sizing: False`, and the module says not to boost risk because the
  required pace is high. Target gap is null when equity marks are stale or missing (`UNVERIFIABLE_EQUITY`). The platform's 10x
  challenge panel should keep the same rule; nothing here changes it.
* States that a premium budget is maximum exposed principal, not a stop loss, and shows a three-full-loss sequence per policy.
* Keeps a frozen `baseline-fixed` policy next to shadow-only variants; matches the platform's frozen-baseline lane (challenge 3).
* Session counts are marked `calendar_verified: False` and an upper bound. Still not read: `sector_rotation.py`, `technical_confluence.py`, its tests.


## Read 2026-11-15 (challenger-f): `technical_confluence.py`

* States up front that price, RSI, EMA, FVG and volume are correlated evidence from one source, reports `independent_data_sources: 1`, and
  labels its confluence count "NOT a probability or entry gate" (`order_authorized: False`).
* Excludes the current New York date's daily bar (it may still be forming), skips repeated dates rather than guessing which revision is final,
  and returns `STALE_CHART_HISTORY` past 8 calendar days. Fewer than 25 usable bars gives `INSUFFICIENT_CLOSED_OHLCV`, not a guess.
* The platform's analogue is the committee and agent votes; those already carry "overlapping candidates are not independent". The same
  honesty applies one level up, to picking the best of many lanes (challenge 14). Still not read: `sector_rotation.py`, the alerter's tests.
