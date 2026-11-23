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
| E6 | Buying calls 1 to 3 trading days AFTER an earnings report beats buying within 7 days BEFORE it. Reported separately for names that ran up more than 10% in the 5 days before the report (buy the rumor, sell the news) and names that fell more than 10% (bad news priced in). Added 2026-11-19 at the owner's request. | Entries within 7 days before earnings |
| R1 | Market-regime guard: skipping NEW puts when the whole market is oversold (SPY RSI14 below 30, or SPY down more than 8% from its 20-day high) or bouncing (SPY up more than 2% on the day) loses less than taking them, and skipping new calls when SPY is overbought (RSI14 above 70) is tested the same way. Added 2026-11-23 at the owner's request after a day when many puts were open into a broad bounce. The guard itself is live as of 2026-11-24 (`regime.py`, several signals not RSI alone, blocks are journalled as SKIPPED_REGIME); the test still needs the regime reading recorded per shadow follow so blocked and unblocked entries can be compared. | Same entries without the guard |
| C1 | The size label (Small, Medium, Large) on an external callout ranks outcomes: Large beats Small after costs. Needs at least 30 resolved callouts per source before any statement (`callouts.py`). Added 2026-11-19. | Same callouts, ignoring the label |

**Pass criteria for all:** independent observations, ask in and bid out plus a stressed exit; the improvement over the frozen
baseline is positive on the **later 30% of dates** (not used to pick the idea) and its 95% bootstrap interval excludes zero; still
positive after removing the three best observations; every extra hypothesis tried makes the bar stricter (count them). Most will
fail, and that is a result. If nothing passes, the next step is a different structure (for example defined-risk spreads), never
looser criteria.

R1, E6 and C1 use the same pass criteria as every row above (independent observations, ask in and bid out plus a stressed exit, later 30% of dates, bootstrap interval excludes zero, still positive without the three best). They need `days_to_earnings` and the 5-day pre-event return, which the shadow book does not record yet; until then they cannot be run. News is never a model input as text: only measurable facts (price moves, dates, volume) are, and a claim from a secondary source is graded below a company filing or a wire report before it is used.

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
