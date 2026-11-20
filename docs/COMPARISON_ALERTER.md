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

## Addendum 2026-11-17: `experiment_desk.py` (alerter at `9eb85e0`)

* **Refuses to leak the future.** A scorecard at a past cutoff blocks equity and realized P&L if the ledger has rows after the cutoff
  (`BLOCKED_FUTURE_LEDGER_ROWS`). The platform's replay/evaluation reads recorded snapshots, so no equivalent leak check was found.
* **Says no winner exists.** `winning_strategy` is None, `verified_profitability` False, `comparison_status` NO_MATCHED_FORWARD_COHORT, and
  raw dollar P&L of independent capital pools is explicitly not used to rank arms. The platform's frozen-baseline lane is the same idea.
* **Weekend "What were we wrong about?"** flags high-score losses, wins with incomplete entry evidence, and the largest win as a share of
  gross profit. The platform's results panel has no largest-win share; candidate for a later display-only change.
* Also in range: `whale_thesis.py` (volume/OI dossiers; same caveat as the platform that volume/OI is not signed flow). Not read in full.

## Addendum 2026-11-18: `sizing.py` (alerter at `9eb85e0`, unchanged since the last run)

* **Size follows an evidence index, and says it is not a probability.** Index = base + 0.006 x score +/- trend match, volume >= OI bonus, spread penalty, IV penalty, small learning nudge, clamped to 0.10-0.90. `calibrated_probability` is always `None`. The platform has no equivalent index; its sizing is the fixed `RiskPolicy` caps, and this run did not touch them (owner decision).
* **Honest caps on thin evidence.** With fewer than 20 real-source closed outcomes the index is capped at 0.78, and with fewer than 10 the profile fraction is capped. Learning only counts real-source outcomes, so demo results cannot inflate sizes. The platform's analogue is the sample-size gate on the Results panel.
* **Skip, do not shrink.** Below a lane's conviction gate the quantity is 0 and the reason is written ("skipped rather than sized small"). Drawdown of 10% and 20% cuts the fraction by 35% and 50%. Goals never raise size (`goal_affects_size: False`).
* **Weakness to keep in mind on the alerter side (not ours to fix):** the index weights are hand-set constants, never fitted; with aggressive paper sizes (owner's choice) a high index only means "more evidence items lined up", so lane P&L judged on few trades says little.
* Platform side: no change. Logged as UX-3 that per-strategy-account sizing and tuning live in the alerter on the Mac and cannot be shown here without faking them.

## Addendum 2026-11-19: `matched_research.py`, `event_risk.py` (alerter at `5dca972`, 11 commits since `9eb85e0`)

* **Pre-registers, then splits samples by registration time.** `matched_research.py` fixes rules (`liquid-trend-fixed-horizons-v1`, registered 2026-11-18 18:00 UTC) and reports observations captured before that as `exploratory` and after it as `forward`. The platform's `exit_replay.py` has a later-30% check but no registration timestamp, so nothing separates "rule written first" from "rule fitted to this data". Worth copying when a hypothesis is registered here.
* **Matched cohorts, one observation per name per session.** Each arm is judged on the same opportunities, with cash counted as zero when a filter skips one (`net_per_opportunity_usd`). The platform's lane comparison does not share a denominator.
* **Unknown stays unknown.** Cases are `PENDING`, `UNOBSERVABLE` or `MEASURED`; forward exits need a time-stamped two-sided quote with spread at most 20%. Both sides pay 0.5% slippage and $0.65 per contract. The platform's exit replay uses ask in, bid out plus a stressed exit, and counts unresolved paths, so it is close in spirit; fees are not modeled there.
* **Calendar coverage is explicit** in `event_risk.py` (`MACRO_START`/`MACRO_END`; outside it the entry is blocked as "coverage unknown"). Platform `events.py` also limits BLS coverage to Nov-Dec 2026 but a lane is not blocked by it; worth checking whether outside-coverage reads as "no events".
* **Weakness on the alerter side:** `SHOCK` percentages are hand-set scenario inputs (labelled illustrative, not betas); the premium-cap and low-OI exceptions are experiments that deliberately loosen entry filters on paper.
* **Still not read:** `server.py`, `handoff_challenge.py`, `opportunity.py`, the alerter's tests.

## Addendum 2026-11-20: `position_plans.py` and the $5K swing account (alerter at `8aa674d`, 7 commits since `5dca972`)

* **An exit level is shown only when the quote is current.** `position_plans.py` gives a modeled exit price for an open position only if the
  quote is not demo, not stale, is a two-sided bid/ask that matches the candidate's fetch time, and (for lane positions) falls inside a US
  session and a maximum age. Otherwise the price is `None` and the status says why (`OBSOLETE_BID`, etc.). It never fills in a guess.
  Platform comparison: `exit_plans` shows stop/target levels computed from entry, which is a rule, not a quote, so it is fine; but the
  dashboard's open-position "mark" should say how old its quote is. Not checked line by line here.
* **Exit rules are saved at entry** (`Saved at entry` vs `Lane defaults`): a later settings change does not silently move the exit of a trade
  already open. Platform lanes read their rules at exit time; whether that can shift an open trade's exit was not checked. Logged as challenge 9.
* **New account, not a resize.** The owner added `$5K paper swing` (5 to 10% per idea, 10% total premium cap, 3x in 30 days stretch goal) as a
  separate account beside the aggressive ones, as CLAUDE.md asks. Platform: no change; sizing there remains the owner's call.
* **Still not read:** `server.py`, `handoff_challenge.py`, `opportunity.py`, the alerter's tests (none run).
