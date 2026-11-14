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

## Addendum 2026-11-14: alerter moved to `48ccf71`

* **Trailing exit is shadow-first and states its own limits.** `EXIT_STRATEGY_RESEARCH.md`: default-disabled toggle, arm at +25%,
  give back 15%, thresholds called "hypotheses, not optimized", the same snapshots compared against 10/15/25% giveback rules, fixed
  stop/target/hold always win, and peaks between scans are admitted to be unobservable. The platform's lanes also only see
  quotes at scan times, so any trailing idea here has the same blind spot. Its exit value is bid minus modeled friction, which is
  the honest direction the platform's stressed exit already points.
* **GEX policy refuses to infer direction.** A price cross of a modeled gamma concentration is labelled a reference cross, not a
  signal; entry-time GEX is frozen and never reused retroactively; unvalidated diagnostic thresholds (2%, 1%, 90 minutes) are named as such.
  The platform's GEX display (2026-11-14) takes the same stance.
* **Goal sprint** (`goal_sprint.py`) pins a frozen baseline policy beside two shadow policies and caps experimental premium, with
  `automatic_execution_authorized: False`. Same shape as the platform's frozen baseline lane.
* **Signal provenance:** `research_foundations.py` lists each signal with origin and validation. The platform now has the same in `docs/SIGNALS.md`.
* **Still not read:** `server.py`, `sector_rotation.py`, `trade_confluence.py`, `technical_confluence.py`, the alerter's tests.
