# How the platform gets better (owner-approved plan, 2026-11-16)

Source: the owner's evolution-plan doc (Claude Doc "How the platform actually gets better"). This file is the copy agents read.

## The problem

Most agent work so far was housekeeping (panels, labels, gates, logs). Almost none of it changed what the platform decides to
buy or sell, and none produced evidence that one rule beats another. The decision code is still small: one entry filter and
score (`LiquidTrendStrategy`), fixed exit percentages (take profit 40, stop 30, expiry margin 5 days), a committee that has seen
a few days of data, and no validated signal (`VALIDATED_SIGNALS` is empty on purpose).

## Owner decisions (2026-11-16)

* A nightly, secret-free export of the paper data to a **private** repository is approved (`src/optplat/export.py`,
  `deploy/export_push.sh`). The platform repo itself is public, so the export must never be pushed there.
* No paid data. Free data only improves execution realism (pricing), not the choice of option. The platform has to show better
  entry and exit decisions on free data before the owner spends anything.
* The daily agent works from this plan. Promotion, risk limits, position-size caps, grading criteria and the broker stay with the owner.

## Phase 1: build the ground truth (the gate below must pass before Phase 2 verdicts count)

1. **Shadow book.** Each scan, follow the top candidates of every strategy and lane (not only the one chosen). Store the
   features known at the time: price, spread, days to expiry, moneyness, IV and its percentile for that name, volume and open
   interest, trend, sector, days to earnings, time of day. Re-quote each followed contract at every scan for about ten trading
   days, then daily out to 30, keeping the **bid path** so any exit rule can be replayed. Always ask in, bid out. Extend the
   existing `tracker.py` rather than building a second store.
2. **Export** to the private data repository (done in code; the owner must create the repository and set `OPTPLAT_EXPORT_REPO`).
3. **Exit replay harness**: replay take-profit, stop, time-stop and trailing rules over the recorded bid paths of the shadow book.
4. **Independent-observation counting**: one observation per underlying per day for any test, so strikes of one name are not counted as many.

**Gate:** at least 20 trading days of shadow book, at least 2,000 followed candidates over at least 50 underlyings, at least 80%
with complete marks, and the export running five days in a row.

## Phase 2: registered hypotheses (use `research.py`; write the pass criteria BEFORE any result exists)

| ID | Hypothesis | Compared with |
| --- | --- | --- |
| S1 | The ranking score predicts anything: top-ranked beats a random pick among candidates passing the same filters | Random pick from the same list |
| E1 | Maximum spread 5% beats 10% after costs | Baseline filters |
| E2 | Buying when IV is low for that name beats buying when it is high | No IV filter |
| E3 | 45 to 90 days to expiry beats 30 to 120 | Baseline range, by DTE bucket |
| E4 | Skipping entries within 7 days of earnings avoids a systematic loser | Entries allowed near earnings |
| E5 | Flagged contracts whose next-day open interest rose beat unconfirmed ones | Unconfirmed flags |
| X1 | Another take-profit/stop pair beats 40/30 (grid 20, 40, 80 by 20, 30, 50) | Current 40/30 |
| X2 | A time stop (5 or 10 days) beats holding to a level | No time stop |
| X3 | A trailing stop after +30% beats a fixed take-profit | Fixed take-profit |
| X5 | Scale out: sell half once the option is up 20% (or 40%), move the stop on the rest to entry (0%), let the rest run to a +80% take-profit; initial stop stays 30%. Idea taken from how a trading community posts lifecycle events (Entered, Trimmed 1/2, Stop to entry, Exit). Registered 2026-11-27 at the owner's request; two rules tried (trim at 20, trim at 40). Mechanised in `exit_replay.py` (`X5 ...` rules). | Current 40/30 |
| X6 | The exit agent (`exit_agent.py`: hold, trim or exit from trend, momentum, spread and gain, with the old stop, expiry window and stop-to-entry kept as floors) beats the fixed 40/30 rule. Registered 2026-11-27 at the owner's request ("the exit agent should take a proper decision, a hard limit doesn't make sense"). It needs the underlying's daily closes at each point of the bid path, which the shadow book does not store yet, so it cannot be replayed until `closes` or its trend features are recorded per point; as of 2026-11-28 each new shadow point stores the underlying's last 21 daily closes (`closes`), so X6 becomes replayable once enough new paths accrue (older points have none); the replay is built as of 2026-11-29 (`exit_replay.replay_agent`, reported under `x6`); until enough new paths with closes accrue the live paper trades under `exit_agent` on are the only evidence and count as one hypothesis tried. | Current 40/30 |
| E6 | Buying calls 1 to 3 trading days AFTER an earnings report beats buying within 7 days BEFORE it. Reported separately for names that ran up more than 10% in the 5 days before the report (buy the rumor, sell the news) and names that fell more than 10% (bad news priced in). Added 2026-11-19 at the owner's request. | Entries within 7 days before earnings |
| R1 | Market-regime guard: skipping NEW puts when the whole market is oversold (SPY RSI14 below 30, or SPY down more than 8% from its 20-day high) or bouncing (SPY up more than 2% on the day) loses less than taking them, and skipping new calls when SPY is overbought (RSI14 above 70) is tested the same way. Added 2026-11-23 at the owner's request after a day when many puts were open into a broad bounce. The guard itself is live as of 2026-11-24 (`regime.py`, several signals not RSI alone, blocks are journalled as SKIPPED_REGIME); the regime reading is recorded per shadow follow as of 2026-11-24 (`regime_label`, `regime_blocks_puts/calls`, `regime_facts`; earlier follows have none), so blocked and unblocked entries can be compared once enough days accrue. | Same entries without the guard |
| C1 | The size label (Small, Medium, Large) on an external callout ranks outcomes: Large beats Small after costs. Needs at least 30 resolved callouts per source before any statement (`callouts.py`). Added 2026-11-19. | Same callouts, ignoring the label |
| D1 | One decider beats the committee vote: a single decision step (`decider.py`) that reads every analyst's note together, decides, sizes by conviction across the whole allowed range (25% of the engine's cap at the 0.45 gate up to 100%) and writes the reason and the invalidation level, beats today's net-score vote and size rule on the same recorded candidates. Analysts stay separate and scored one by one; only the combining step changes. Added 2026-11-25 at the owner's request ("one big trader, not eight"); built and REGISTERED 2026-11-28 at the owner's go-ahead. Runs in shadow only (journal kind `DECIDER`, beside `COMMITTEE`); it places no order until it passes. | Today's committee net score and size rule |
| X4 | A buffer on the VWAP exit of the short-term option lanes beats exiting on the first bar that closes through VWAP: exit only when the underlying closes beyond VWAP by a set margin (for example 0.1 of the day's average bar range), or on two bars in a row, and not in the first N bars after entry. Added 2026-11-25 at the owner's request after many trades ended as "Lost VWAP". The entry is the EMA9 crossing VWAP, so price starts at VWAP and one wobble closes the trade. Needs recorded intraday bars per trade to replay, which the shadow book does not hold for the lanes yet. | Exit on the first bar that closes through VWAP |
| SW1 | The swing pullback lane (`swing-pullback`, shares) beats SPY over the same dates after costs. Registered 2026-11-26 on the owner's instruction, criteria set by the agent at the owner's request. Mechanised in `lane_hypotheses.py`. | SPY close-to-close over each trade's dates |
| ST1 | The short-term EMA9/VWAP lane (`shortterm-ema9-vwap`, shares) has positive expectancy per trade after costs. Registered 2026-11-26 as SW1. | Zero (an intraday long's drift) |

X5 pass criteria, fixed before any result: the same bar as every row (stressed-exit return, later 30% of dates positive with the 95% bootstrap interval excluding zero, still positive without the three best), at least 60 independent resolved observations, and each of its two rules counts as an extra hypothesis for the stricter bar. The blended return is half the trim return plus half the return of the rest, both at the bid (stressed: bid minus half the spread); a gap through the stop-to-entry level sells at that bid, not at entry. Measurement only: it changes no live exit threshold.

X6 pass criteria, fixed before any result (2026-11-29): the same bar as every row (stressed-exit return, later 30% of dates positive with the 95% bootstrap interval excluding zero, still positive without the three best), at least 60 independent paired observations whose whole path carries closes, one observation per underlying per day. The replay holds two contracts, so the agent can trim half; a trimmed position blends the trimmed half 50/50 with the rest, trim and exit at the bid (stressed: bid minus half the spread). A path with any usable point lacking closes is unresolved (`no_closes`), never replayed with the agent's fixed-rule fall-back. The agent's floors (expiry window, 30% stop, stop to entry) stay. It counts as one extra hypothesis for the stricter bar. Measurement only; promotion is the owner's.

D1 pass criteria, fixed before any result: at least 20 trading days of shadow decisions and at least 60 candidates with a 24-hour forward return from recorded data; one observation per underlying per day; the contract-weighted dollar change of the decider's choices minus the committee's, ask in and bid out, is positive on the later 30% of dates with its 95% bootstrap interval excluding zero, and still positive without the three best candidates. A REJECT counts as zero contracts on its side. `GET /api/decider/compare` is the descriptive running tally only, not the test. If it passes, promotion to a paper decision is the owner's call.

**Pass criteria for all:** independent observations, ask in and bid out plus a stressed exit; the improvement over the frozen
baseline is positive on the **later 30% of dates** (not used to pick the idea) and its 95% bootstrap interval excludes zero; still
positive after removing the three best observations; every extra hypothesis tried makes the bar stricter (count them). Most will
fail, and that is a result. If nothing passes, the next step is a different structure (for example defined-risk spreads), never
looser criteria.

R1, E6, C1, D1 and X4 use the same pass criteria as every row above (independent observations, ask in and bid out plus a stressed exit, later 30% of dates, bootstrap interval excludes zero, still positive without the three best). E6 now has a mechanical entry-replay group (`entry_replay.e6`, 2026-11-26: calls 1-3 days after a report vs 0-7 days before; the 10% run-up/fall split is not run because the exact pre-report return is not recorded). X4 needs recorded intraday bars, which the shadow book does not hold; until then it cannot be run. News is never a model input as text: only measurable facts (price moves, dates, volume) are, and a claim from a secondary source is graded below a company filing or a wire report before it is used.

SW1 and ST1 criteria, fixed before any confirmatory result (`src/optplat/lane_hypotheses.py`): only trades OPENED from 2026-11-27 count (earlier ones were visible when this was written); one observation per name per New York entry day; an extra 0.20% (SW1) or 0.10% (ST1) cost on every trade on top of the recorded 0.05% slippage each way; a **fixed sample** (first 60 observations for SW1 across at least 20 names and 15 days, first 100 for ST1 across at least 20 days) and one final verdict on it, so later trades cannot rescue it; the plan's bar on that sample (later 30% of dates positive with its bootstrap interval excluding zero, Bonferroni-corrected to 97.5% for the two tested together, and still positive without the three best). A sample too concentrated in days or names fails instead of waiting. SW1 with more than 10% of trades lacking SPY closes gives no verdict. Run read-only with `python -m optplat.lane_hypotheses --db <path>`.

## Phase 3: where AI goes

The trader stays rule-based. AI works offline: (a) a learned scorer trained walk-forward on the shadow book (regularised
logistic regression or small boosted trees), run in shadow with predictions written down before outcomes, earning a paper lane
only by passing the same criteria; (b) a weekly research agent that evaluates registered hypotheses, writes the post-mortem and
registers the next ones; (c) the committee's weights, which count only once each agent has enough resolved votes and are frozen
between releases. Language models never place orders.

## Rules for each daily run

* Every change must say which decision or hypothesis it helps. Display-only work is allowed only when it is needed to run or read the research.
* Until the Phase 1 gate: advance the shadow book, the export or the replay harness. After it: register or evaluate hypotheses.
* Append one line to `docs/EVOLUTION_LOG.md` every run: followed candidates, days of shadow book, hypotheses registered and resolved, best verified improvement over the frozen baseline (or "none").
* Report plainly when the evidence is too thin. Never present simulated results as real or as proof of an edge.
