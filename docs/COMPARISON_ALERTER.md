# Platform vs. options-alerter

Alerter reviewed up to commit `a7a2ca0`. The alerter is the owner's private research app; this
platform is the safety-first execution skeleton. Notes are from code reading only; neither
repo's real results are visible from here.

| Area | options-alerter | options-platform |
|---|---|---|
| Fills | Modeled ask+friction buys, bid-friction sells (`strategy_performance.py`); marks itself `modeled_not_broker_fills` | Sim broker: ask+0.5% slippage, limit must cover it, never fills from a missing quote |
| Result reporting | Per-lane closed-trade summary; win rate is `null` with zero trades; drawdown labelled "closed-trade only, NOT account max drawdown"; open equity is `null` if any mark is unusable | None before this change; now `/api/results` (see below) |
| Competitor claims | Imported rival trades are labelled unverified; "winner" is always `None` | n/a |
| Sizing | Confidence-scaled (owner decision 2026-11-15), conviction gates | Fixed risk limits; not to be changed by agents |
| Research breadth | Lanes, session replay, GEX, sector rotation, $1K challenge account | One baseline strategy, recorder, no replay yet |

Also read (run 2): `day_limits.py`. Per-day entry limits (realized-loss cap counting the worst case
of the new entry, max entries per day, ET entry window) that only ever add failures to an entry,
are OFF until the owner sets them, and report `NOT_CHECKED_NO_CLOSED_LEDGER` instead of passing
silently when they cannot be measured. Same fail-closed spirit as the platform; relevant to backlog 3.

Where the alerter is more honest: it labels every number's provenance and refuses to total
separate virtual accounts. Where the platform is stricter: fail-closed risk, order state machine,
PAPER-only enforcement, quote-time verification.

Also read (run 3): `local_reports.py` and `liquidity.py`. The alerter writes write-once, 0600, dated
session/weekend JSON archives beside its DB (so release swaps never erase history) and refuses to
back-date an unobserved quote; its calendar is labelled "estimated". `liquidity.py` scores volume, OI,
spread and size-vs-volume and labels exit estimates `SCENARIO_ONLY`. The platform has no liquidity or
position-size-vs-volume check on entries (idea for a future run; it would be a risk change, so owner
decision) and no durable dated archive beyond SQLite retention.

Also read (run 4): the alerter's `static/app.js`/`index.html`/`tests/ui_contract.cjs` redesign (#40).
It puts a decision verdict first, keeps unmarkable accounts as "unknown" rather than zero, prioritises the
emergency stop over partial API faults, labels partial/stale evidence, and tests this in a Node contract test.
The platform dashboard is a flat single page with no such contract test (only an innerHTML ban); the new
Results panel borrows the "unknown stays unknown" rule. A fuller decision-desk layout is future UX work.

Also read (run 5): `gex.py`. Its header says plainly that open interest does not reveal dealer inventories and
that the call-positive/put-negative sign convention is an INVENTED INVENTORY ASSUMPTION; it refuses a partial
result when the row cap is hit and counts omitted rows. The platform's `ChainRow` already carries `iv` and
open interest, so a net-GEX view is feasible here without new data (correcting the earlier note in
CHALLENGES row 6); it must carry the same assumption label. Alerter unchanged since `a7a2ca0` this run.

Also read (run 6): `market_breadth.py`. It ranks a broad list (up to 320 names, batches of 20) on one-day change and
volume relative to the prior five days, labels the output "indicative daily bars, not live quotes" and says the rank is
NEVER a win probability; tickers the provider fails on stay `DATA_UNAVAILABLE` / `INSUFFICIENT_HISTORY` rather than
being dropped quietly. The platform's candidate score had no such label on the dashboard; the new Top candidates panel
now states the score is a ranking heuristic, not a chance of profit. The platform has no breadth/discovery step: it
only scans the owner's watchlist. Alerter unchanged since `a7a2ca0` this run.

Also read (run 7): `gex.py` again for implementation. Same formula now in `optplat/gex.py` (Black-Scholes gamma, r=4%, one-day floor
for 0DTE, 45-day window, call+/put-). Difference: the alerter returns a per-strike table and heatmap and refuses to
publish when its row cap is reached; the platform only returns a total and the largest +/- strike from whatever sample
the provider gave, labelled partial. Alerter unchanged since `a7a2ca0`.


## `sizing.py` (read 2026-11-15, run 8)

The alerter sizes from an ordinal evidence index (score, trend match, volume vs open interest, spread, IV), explicitly
"not a win probability". It caps the index at 0.78 until 20 learning samples exist, caps the fraction until 10, shrinks
size at 10% and 20% drawdown, and states that goals never raise risk. Lane policy (owner-chosen) maps the index to a
percent-of-equity band. The platform uses a fixed 1% worst-case cost per order from `RiskPolicy`; any move toward
confidence-scaled sizing is a risk-policy decision for the owner (CLAUDE.md), so it is not attempted here. Worth copying
when the owner decides: the sample-count caps and the drawdown shrink, both of which make sizing more cautious when evidence is thin.


## `unusual_activity.py` (read 2026-11-15, run 9; alerter now at `80672a6`)

A Mac-only "turnover radar" over the Yahoo chain: volume >= 150 and volume/OI >= 3, or volume >= 500 when OI is zero or
missing. It never turns zero/missing OI into an infinite ratio, labels OI state (`REPORTED`, `REPORTED_ZERO`, `MISSING`),
states that ask x volume is a proxy and not traded premium, and says a high rank never bypasses the entry-quality veto.
Extreme rows (ratio >= 20, volume >= 5000) are kept as a per-day high-water mark, never summed across scans. Platform
difference: `strategy.py` treated a missing volume/OI as 0 silently (fail-closed, right), but the skip reason lumped it
in with "too low". Run 9 separates the two in the explanation and shows volume and OI (or "not reported") per candidate.
The platform has no turnover/anomaly radar and no per-day history; that needs recorded chains (backlog) and is not faked.

## `strategy_performance.py` (read 2026-11-16, run 10; alerter still at `80672a6`)

Mac-only per-strategy-account report (`performance_report`). What it does that the platform does not yet:

* Every account carries `paper_equity_usd` that is `null` when any option mark is missing, stale or unusable, plus a count of
  `unreliable_option_marks`. The platform's `/api/results` already does the same for unrealized P&L (run 2).
* The report states its fill model in a field (`order_execution`: modeled ask plus friction on buys, bid minus friction on
  sells) and sets `source_quote_timestamp_verified` to false. The platform's results payload does not yet say how fills are
  modeled; its limitations list is free text. Challenge row 7.
* A closed-trade equity curve (last 90 points) next to a drawdown labelled "closed-trade-only, NOT account max drawdown".
  The platform has the closed-only drawdown but no curve.
* Partial exits and "principal recovered" are tracked per position; the platform has single full exits only.
* A competitor comparison that refuses to name a winner: only user-supplied, explicitly dated trades, matched by contract and
  entry day, labelled unverified. Worth copying in spirit: never compare against another system's headline numbers.
* Scope notes say balances of separate virtual accounts must never be summed as real capital.


## `entry_quality.py` (read 2026-11-16, run 11)

Strict new-entry gate for real-source paper options ("observation is not authorization"; no score may waive it).

* Spread limit is a share of the ASK (15%); the platform measures spread against its own configured limit. Compare the
  denominators before comparing numbers.
* Zero bid fails the entry ("exit price not observable"). The platform's `propose` rejects invalid quotes, but a test pinning a
  zero-bid case would be worth checking (not done this run).
* Volume and open interest minimums (20 / 100), missing counts as failure, same as the platform (run 9 pinned it).
* Per-side concentration caps (same symbol 2, market ETFs 3, growth tech 4). The platform has a same-underlying concentration limit, but no
  group caps (market ETFs, growth tech). Needs an owner decision (risk policy), logged in CHALLENGES.
* Strike-distance screen by horizon and a 7-730 DTE window; the platform has a single DTE window.
* Every failure is a plain-language reason list, which is the pattern the platform's `explain_no_proposal` copies.

## `day_limits.py` (read 2026-11-16, run 12; alerter still at `80672a6`)

* Per-day entry limits ported from an MIT-licensed day-trader risk manager: `daily_loss_limit_usd`, `max_entries_per_day`,
  `entry_window_et`. All OFF until set; they only ever add failures to a new entry, never close or resize anything.
* Loss check counts realized loss so far today plus the most the new entry could lose (premium, or the modeled stop percent when
  auto-exits are on, and says that is modeled). "Today" is the New York date.
* Honest about gaps: strategy-lane accounts have no closed ledger in this view, so the result is `NOT_CHECKED_NO_CLOSED_LEDGER`
  instead of a pass. The platform has no daily loss halt at all yet (backlog 3; the default value is a risk decision for the owner).
* Platform difference: it fails closed on missing data but has no per-day counters.

## `daily_review.py` (read 2026-11-16, run 13; alerter still at `80672a6`)

* A once-per-day, proposals-only report stored in `daily_platform_reviews`: 24h audit counts, skip/reject reason tallies, liquidity tier mix, and
  findings. It states in its header that a report cannot authorise trades, change risk settings or promote skills.
* Operational problems come first: unreliable held-option marks are an `OPERATIONAL_BLOCKER` and the fallback equity is called non-executable.
  GEX and unusual-activity findings are only counted when fresh (24h) and from a scan that did not error; partial expiry coverage is flagged.
* Honest about gaps: "zero completed paper exits despite open positions; outcome-based learning is not yet validated".
* Platform difference: no daily report and no per-day audit tally of skip reasons (only the last cycle's `explain_no_proposal`). A daily
  rollup of skip reasons is a possible later step; it needs recorded cycle reports, which the platform does not yet persist.

## `exit_decisions.py` (read 2026-11-16, run 14; alerter still at `80672a6`)

* Local-only exit research: a deterministic "shadow" rule set (adverse trend, expiry within 14 days, early profit/loss tests) that only
  proposes EXIT/HOLD; hard stop/target/holding rules keep precedence. The optional Ollama model path accepts loopback endpoints only
  and is labelled a paper simulation, "not an observed edge".
* Honest about gaps: insufficient trend evidence returns HOLD with that reason, and stale quotes or missing contracts never create fills.
* Platform difference: exits are fixed take-profit/stop-loss only (backlog 5 trailing stop); there is no shadow-exit research log.
