# Comparison: options-platform and options-alerter

Written 2026-11-12 against alerter commit `9210fd8`. The alerter is the ChatGPT-built private repo; this platform is the
Claude-built one. This is a code-reading comparison, not a performance comparison: neither project has produced evidence
of a trading edge, and nothing here should be read as saying one earns more than the other.

**What was read:** the alerter's README, `PRODUCT_DECISION_ARCHITECTURE.md`, `CHANGELOG.md`, `RELIABILITY_AUDIT.md`,
`gex.py`, `unusual_activity.py`, `entry_quality.py`, `liquidity.py`, `risk.py`, `sizing.py`, `strategy_lanes.py`,
`intraday_strategy.py`, `exit_decisions.py`, `feedback.py`, `adaptive.py`, `agent_lab.py`, `research_foundations.py`,
`daily_review.py`, two agent skill files and the CI workflow. **Not read:** `agents.py`, `core.py`, `storage.py`,
`server.py`, `data_sources.py`, the other skill files, and its tests (none were run). Claims about those are not made.

**Read on 2026-11-12 (daily challenger run):** `agents.py` and `core.py`, plus the skeptic skill file. See "Second reading" at the end.

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

## Second reading: `agents.py`, `core.py`, skeptic skill (2026-11-12, alerter `9210fd8`, unchanged since the first comparison)

* **Models can only make it stricter.** `agents.py` lets an optional local Ollama model add risks or raise a VETO, but never
  upgrade a rejection; the CIO is downgraded to REJECT if the model vetoes. Endpoints other than localhost are ignored so
  trading data is never sent out. The platform's research lanes have no model in the loop, so there is nothing to port, but
  the "can only tighten" rule is the right one if a model reviewer is ever added.
* **A loss tripwire on peer groups.** In `core.research_case`, if a cohort has at least 8 closed trades with mean return at or
  below -30% and a win rate at or below 25%, the skeptic moves from PASS to REVISE and the CIO to WATCH. Past gains never relax
  a veto. The platform has no equivalent: a lane that keeps losing keeps trading. Candidate for a later, owner-approved change
  (it alters what lanes trade, so it is not done here).
* **Scores are capped when the data is thin.** `candidate_score` caps the score at 52 to 56 for volume under 5, open interest
  under 20 or spread over 20%, so a tiny denominator cannot top a ranked list. The platform tags thin trades afterwards.
* **Honest labels.** The alerter's score is described as a ranking heuristic, never a probability. Same stance as here.
* **Black-Scholes greeks with stated assumptions** (4% rate, no dividends). Not needed by the platform yet.
* **Not read:** `storage.py`, `server.py`, `data_sources.py`, the other six skill files, tests (none run).

## Addendum 2026-11-12 (second run): `storage.py`

Read the alerter's `storage.py` (commit `9210fd8`, unchanged). Observations, not verdicts: it merges per-ticker research
state inside one `BEGIN IMMEDIATE` transaction so concurrent workers cannot overwrite each other; it keeps a `trade_journal`
that stores the council's review text at entry next to the exit result; and a partial unique index allows only one open
position per candidate. The platform's SQLite store already uses transactions per operation; the entry-time review snapshot is
roughly what `lane_trades` payloads and post-mortems hold. Still not read: `agents.py`, `core.py`, `server.py`, `data_sources.py`.
Ported today: the provenance idea (`research_foundations.py`) as `provenance.py`.

## Third reading (2026-11-13, alerter still at `9210fd8`)

Read `data_sources.py`. Points that matter here:

* **GEX needs both sides.** It samples up to six near expiries in full (all strikes, including zero volume) and marks an
  expiry as failed when calls or puts are missing. Past a row cap it refuses to compute rather than return a biased number.
  It labels coverage `SAMPLED_OPTIONS_CHAIN` or `ALL_LISTED_NEAR_EXPIRIES_ATTEMPTED`. Our `signals.gex` summed whatever rows
  were present, so a calls-only sample looked like a large positive exposure. It now reports `net_is_interpretable`.
* **Held contracts are pinned.** The scan always fetches the exact held contract ids and reports `held_missing` ("no
  quote-backed exits for them") instead of substituting another. Not checked whether the platform's exit path fails the same way.
* **Free-data honesty.** Every scan returns a `limitations` list (no exchange timestamp, delayed chains, volume does not
  identify the counterparty). The platform has similar text per lane; not per scan.
* **Candidates that fail quality gates are kept and labelled** (up to five) for hypothesis tracking, as our decision journal does.

Still unread: `server.py`, the other skill files. Alerter tests have not been run.

## Fourth reading (2026-11-13, second run, alerter still at `9210fd8`)

Read `sizing.py` and the position-sizing skill.

* **Size is advisory and subordinate.** The sizing result becomes NO_TRADE unless the Skeptic says PASS and the CIO says
  SUBMIT_FOR_RISK. Goals are tracking only ("falling behind does not increase risk budgets").
* **Participation caps on free data.** For yfinance candidates, quantity is capped at fixed shares of daily volume and open
  interest, and refused when the entry-quality check fails. The platform only tags this after the fact (challenge 10).
* **Confidence is capped by sample size.** The evidence index is held at or below 0.78 under 20 comparable closed trades, and
  the fraction under 0.60 (0.45 balanced) under 10. The platform's scoreboard has the same stance: too few trades, no verdict.
* **Drawdown shrinks size** (x0.65 at 10%, x0.5 more at 20%). The platform has no drawdown-scaled size; that is a risk
  policy question for the owner.
* Still unread: `server.py` and six of the seven skill files. Alerter tests not run.
