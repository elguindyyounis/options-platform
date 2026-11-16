# Challenges (platform vs. alerter)

Last alerter commit reviewed: `80672a6` (unchanged at run 18)

## Open challenges

| # | Challenge | Needs owner? |
|---|---|---|
| 1 | No commissions/fees in paper fills; results look better than reality. Needs a fee model value. | Yes (cost assumption) |
| 2 | Win/loss stats on few trades. Addressed in part: `/api/results` sample gate plus (2026-11-15 run 3) a chronological split-half stability check. Still no true out-of-sample test or baseline comparison (backlog 2). | No |
| 3 | Alerter judges many lanes on few trades; platform has one strategy but no multiple-testing note once variants exist. | No |
| 4 | ~~Open-position losses invisible~~ Addressed 2026-11-15: `/api/results.open_positions` marks to bid with verified fresh quotes; total is null if any position is unmarkable. Still no equity curve or recorded-quote marking. | No |
| 5 | Alerter's day limits (`day_limits.py`) are all OFF until set and say `NOT_CHECKED` when the ledger cannot measure them; platform has no daily loss halt yet (backlog 3, default is a risk decision). | Yes (default value) |
| 6 | **UX:** `/api/results` existed only as JSON, so the dashboard showed a bare win rate with no sample warning (fixed 2026-11-15 run 4: Results panel). Why-skipped in plain words done (run 5: Decisions panel + `explain_no_proposal`). Top candidates done run 6 (cycle report `candidates`, dashboard panel). Net GEX done run 7 (cycle report `gex` + dashboard panel, labelled an invented-inventory assumption on a sample chain). Run 8 added an "At a glance" strip (safe? acting? needs you?) with unknown data shown as a warning, never as fine. Still missing from the owner's mock-up: per-account performance/tuning, calendar. The calendar needs a trustworthy event source (owner). Per-account tuning is alerter-only (Mac DB, not visible here). Run 9: candidates now show volume and open interest, and an unreported value reads "not reported", never 0. | Partly |
| 7 | Alerter's performance report names its fill model in a field (`order_execution`, modeled ask+friction / bid-friction) and sets `source_quote_timestamp_verified=false`; the platform's `/api/results` only lists limitations as prose. Also no closed-trade equity curve. Run 11: fill model now named in `/api/results.fill_model` and on the dashboard; equity curve still missing. | No |
| 8 | **UX (run 10):** the glance strip never said whether the market was open, and could not tell a stopped loop from a stalled one or show that the market-hours check was switched off. Fixed in run 10 (see log). Still open from the mock-up: per-account performance/tuning (alerter-only, Mac DB), calendar (needs an event source from the owner), Monday plan page (needs real data; Yahoo is unreachable from cloud runs). | Partly |
| 9 | **UX (run 11):** the Results panel showed P&L but not how fills were simulated, so a reader could not tell the numbers assume immediate fills at ask/bid plus slippage with no fees. Fixed: `fill_model` row (unknown brokers read "unknown", never "conservative"). Also found: the alerter caps same-side exposure per symbol and group (`entry_quality.py`); the platform limits only same-underlying exposure, not groups. Group caps are a risk-policy change. | Yes (concentration caps) |
| 10 | **UX (run 12):** "stalled" was only a dashboard guess from the last cycle start; a loop whose cycles all fail (and so look recent) still read as healthy, and nothing server-side said how long since a success. Fixed: `Runner.status()` now reports `last_success_at`, `last_failure_at`, `consecutive_failures`, `seconds_since_success` and `stalled`; glance shows failure streaks and server-reported stalls. `/api/health` left unchanged on purpose (unauthenticated). Still missing: calendar (needs an event source), per-account tuning (Mac only), daily loss halt (default is a risk decision, see 5). | Partly |
| 11 | **UX (run 13):** Results showed totals and drawdown but not the path: a positive total could hide a long slide. Added `cumulative_pnl_recent_usd` (last 20 closed trades, time order) and `longest_losing_streak` to `/api/results` and two text-only Results rows. Still no chart and no curve including open marks; the curve uses the same optimistic, fee-free fills. Calendar and per-account tuning remain blocked (event source / Mac-only). | No |
| 12 | **UX (run 14):** the Decisions panel explained only the last cycle, so a reader could not tell whether "nothing met the rules" was one quiet cycle or the pattern for the last day. Fixed: the engine keeps a bounded (50 cycles) tally of entry result codes, shown in `/api/engine/status.recent_outcomes` and as one line under Decisions. Counts result codes only (not reasons); it is not a per-day rollup and is not an evidence of edge. Per-account tuning (Mac only) and calendar (event source) still blocked. | No |
| 13 | **UX (run 15):** Open positions showed cost and mark but not what the rules would do with them; a reader could not tell, before it happened, at which bid a position sells or whether exits are even on. Added display-only `exit_plan` (take-profit bid, stop bid, expiry-exit window) to `/api/engine/status.exit_plans` and three Open-positions columns plus a note saying whether automatic exits are ON or OFF. Levels are bid-based rules, not predictions; fills stay simulated and fee-free. Calendar (event source) and per-account tuning (Mac only) still blocked. | No |
| 14 | **UX (run 16):** nothing on the dashboard said what the owner is being asked to decide or what evidence is still missing, so a green-looking P&L could read as "ready". Added display-only `promotion` to `/api/results` (`promotion_recommended` always false, `evidence_missing` list: sample size, out-of-sample holdout, do-nothing baseline, fee model, timestamped quotes/real fills) and a "Ready to promote beyond paper?" row. Copied from the alerter's `strategy_postmortems.py`. The list is a checklist, not a test; the platform still has no holdout or baseline run (backlog 1-2). Calendar (event source) and per-account tuning (Mac only) still blocked. | No |
| 15 | **UX (run 17):** challenge 1 (no fees) was only a sentence in the limitations; a reader could not tell how fragile the simulated profit is. Added display-only `breakeven_fee_per_contract_usd` and `contracts_closed` to `/api/results` and a "Fee headroom" Results row: the round-trip fee per contract that would erase realised P&L. It is derived from the fills, no fee is assumed (null when P&L is not positive). Real fees, slippage and queue effects still come on top. Calendar (event source) and per-account tuning (Mac only) still blocked. | No |
| 16 | **UX (run 18):** a decision to buy showed quantity but not how big that is against the contract's reported volume and open interest; with confidence-driven sizing a large order in a thin contract would read as fine. Added display-only `size_vs_liquidity` per entry (percent of reported volume/OI, warning over 10%, copied from the alerter's `liquidity.py`) and a "Size check" in the Decisions Why column. It never blocks or resizes anything; a block would be a risk-policy change for the owner. Volume/OI are delayed provider numbers and paper fills ignore size impact. Calendar (event source) and per-account tuning (Mac only) still blocked. | No |
| 17 | **Owner request (2026-11-16):** look at unusual single-contract flow (huge volume vs tiny OI, big premium, correlated names like SMH/MU) and fit it to the strategy. Added a display-only radar (`flow.py`, `flow` and `flow_themes` in the cycle report, a dashboard panel) and `docs/FLOW_CRITERIA.md`. It cannot see ask-side or multi-leg share (free chain), so those read "not available". The platform's strategy would not trade any of the examples (far OTM, low OI); making flow a trigger is a strategy/sizing decision. The alerter already has this radar and the accounts are Mac-only, so see `docs/ALERTER_FLOW_HANDOFF.md`. Also asked: both apps reachable by typing a URL with nothing typed in a terminal. The platform needs a running process and its token; an always-on Mac service for it is a one-time owner setup and an auth/start-up decision, not done here. | Yes (flow as trigger; Mac auto-start) |
| 18 | Flow-following paper strategies exist (`flow-otm`, `flow-near`) but nothing measures them: no replay, no baseline, flagged volume cannot show who bought. They are blocked by the risk gate when under 7 days to expiry or spread over 15%; relaxing that is an owner risk decision. Samples will be tiny. | Yes (risk limits, promotion) |

## Run log

* 2026-11-16 (run 18c, owner message): Owner wants out-of-the-money flow contracts considered, with a nearer-the-money variant acceptable. Added `FlowFollowStrategy` (`flow-otm`, `flow-near`), selected by `OPTPLAT_STRATEGY`, default unchanged. Risk policy untouched. 5 new tests; 205 pass. Weakness: no evidence flow direction means anything; compare to a do-nothing baseline via replay (backlog 1-2) before trusting it.

* 2026-11-16 (run 18b, owner message): Added the unusual-turnover radar (display only), `FLOW_CRITERIA.md`, `ALERTER_FLOW_HANDOFF.md`. 4 new tests; 201 pass.

* 2026-11-16 (run 18, Monday so no weekend scan): Alerter unchanged (`80672a6`); read `liquidity.py` (see COMPARISON_ALERTER).
  UX challenge: order size was not shown against liquidity. Added display-only `size_vs_liquidity` to each entry and a Size check
  in the Decisions panel. No risk, order, auth, sizing or broker code touched. Weaknesses noted: the alerter scores and tiers
  liquidity and runs bid-concession exit stress; the platform has only a volume/OI floor and immediate, impact-free paper fills.
  1 new test; 197 pass. The Mac copy is a manual git clone: merged code is not on the Mac until the owner pulls.

* 2026-11-16 (run 17, Monday so no weekend scan): Alerter unchanged (`80672a6`); re-read `risk.py` (see COMPARISON_ALERTER).
  UX challenge: simulated profit looked solid because fees are not modeled. Added fee-headroom (break-even round-trip fee per
  contract) to `/api/results` and the Results panel. Display only; no risk, order, auth, sizing or broker code touched. Weaknesses
  noted: the alerter's risk gate rejects stale (>30 min) or unverifiable quotes and caps spread at 35%, and states "unofficial
  delayed chain" as a warning on every yfinance candidate; the platform's results panel still has no fee assumption. 1 new test;
  196 pass. The Mac copy is a manual git clone: merged code is not on the Mac until the owner pulls.

* 2026-11-16 (run 16, Monday so no weekend scan): Alerter unchanged (`80672a6`); read `strategy_postmortems.py` (see COMPARISON_ALERTER).
  UX challenge: no place said what is still missing before a strategy could be promoted. Added `promotion` block (never recommends;
  lists missing evidence) to `/api/results` and one Results row. No risk, order, auth, sizing or broker code touched. Weaknesses noted:
  the alerter predeclares a hypothesis, falsification rule and baseline per lane before trading, the platform has none for its one
  strategy; the checklist is static text. 2 new tests; 195 pass. The Mac copy is a manual git clone: merged code is not on the Mac
  until the owner pulls.

* 2026-11-16 (run 15, Monday so no weekend scan): Alerter unchanged (`80672a6`); read `session_replay.py` (see COMPARISON_ALERTER).
  UX challenge: Open positions did not say where they would be sold or whether automatic exits were on. Added display-only
  `exit_plan` levels and a note. No risk, order, auth, sizing or broker code touched. Weaknesses noted: the alerter's replay
  withholds any conclusion under 30 historical triggers and labels results stock-direction odds, not option P&L, while the
  platform still has no replay or baseline (backlog 1-2); exit levels use the bid with immediate simulated fills. 3 new tests;
  193 pass. The Mac copy is a manual git clone: merged code is not on the Mac until the owner pulls.

* 2026-11-16 (run 14, Monday so no weekend scan): Alerter unchanged (`80672a6`); read `exit_decisions.py` (see COMPARISON_ALERTER).
  UX challenge: Decisions showed one cycle only. Added a rolling outcome tally (last 50 cycles, in the store's state table,
  display only) to engine status and the Decisions note. No risk, order, auth, sizing or broker code touched. Weaknesses noted: the
  alerter's shadow exits are research-only and labelled, while the platform has no exit research at all; the tally counts result
  codes, so reasons inside NO_PROPOSAL are still last-cycle only. 2 new tests; 190 pass. The Mac copy is a manual git clone: merged
  code is not on the Mac until the owner pulls.

* 2026-11-16 (run 13, Monday so no weekend scan): Alerter unchanged (`80672a6`); read `daily_review.py` (see COMPARISON_ALERTER).
  UX challenge: Results gave totals but not the path. Added cumulative closed P&L (last 20) and longest losing streak to
  `/api/results` and the Results panel. Display only; no risk, order, auth, sizing or broker code touched. Weaknesses noted: the alerter
  puts operational blockers (unreliable marks) above trading findings; the platform has no daily rollup of skip reasons. 2 new tests;
  188 pass. The Mac copy is a manual git clone: merged code is not on the Mac until the owner pulls.

* 2026-11-16 (run 12, Monday so no weekend scan): Alerter unchanged (`80672a6`); read `day_limits.py` (see COMPARISON_ALERTER).
  UX challenge: runner health was a client-side guess and a loop failing every cycle looked fine. `Runner.status()` now carries
  success/failure times, a failure streak and a server-side `stalled` flag (3x interval from last success, or from start);
  glance shows it. No risk, order, auth, sizing or broker code touched. Weaknesses noted: the alerter's day limits are
  stricter than the platform's nothing-at-all (daily loss halt still open, owner must pick the default); `stalled` detects a
  stuck or failing loop, not wrong data. 2 new tests, glance node test extended; 186 pass. The Mac copy is a manual git clone:
  merged code is not on the Mac until the owner pulls.

* 2026-11-16 (run 11, Monday so no weekend scan): Alerter unchanged (`80672a6`); read `entry_quality.py` (see
  COMPARISON_ALERTER). UX challenge: Results panel hid the fill assumptions. Added `describe_fill_model` and `fill_model` in
  `/api/results`, plus a "How fills are simulated" row (text only). Display only; no risk, order, auth, sizing or broker code
  touched. Weaknesses noted: slippage is a flat percent with immediate fills (no queue, partials or impact), so paper fills are
  optimistic by construction; correlated-exposure caps missing. 2 new tests, 1 extended; 184 pass. The Mac copy is a manual git
  clone: merged code is not on the Mac until the owner pulls.

* 2026-11-16 (run 10, Monday so no weekend scan): Alerter unchanged (`80672a6`); read `strategy_performance.py` (see
  COMPARISON_ALERTER). UX challenge: "At a glance" did not state market open/closed, did not warn when the market-hours check
  is off, and a loop that claims to run but has not started a cycle in 3x its interval looked healthy. Added those lines to
  `buildGlance` (optional `nowMs` argument for testing). Frontend only; no risk, order, auth, sizing or broker code touched.
  Weaknesses noted: the stall check trusts the cycle's own `started_at`, so it only catches a stuck loop, not wrong data;
  the stall rule duplicates backlog item 4 (server-side runner health), which is still the better home. Existing glance test
  extended (closed/market-hours-off/stalled and fresh cases); 182 pass. The Mac copy is a manual git clone: merged code is not on
  the Mac until the owner pulls.

* 2026-11-15 (run 9): Alerter moved to `80672a6` (volume/OI anomaly radar, Mac-only; read `unusual_activity.py`).
  UX challenge: the Top candidates panel gave a score but not the liquidity behind it, and a skipped contract with
  missing volume/OI was reported as "too low", which blurs "the provider sent nothing" with "the market is thin".
  Added volume and open interest to cycle-report candidates and two dashboard columns ("not reported" for null), and a
  separate skip reason for unreported volume/OI. Display only: `propose` unchanged (missing still fails closed, a test
  pins that). Weaknesses noted: the candidate score still adds `min(OI,5000)/500`, so it leans on OI that is a prior-day
  snapshot; the platform has no turnover radar or per-day history (needs recorded chains). 182 pass (1 new test, 1 updated
  to include the new fields). Weekend scan: Yahoo still refused (HTTP 000); MONDAY_PLAN says so. The Mac copy is a manual
  git clone: merged code is not on the Mac until the owner pulls.

* 2026-11-15 (run 8): Alerter unchanged (`a7a2ca0`); read `sizing.py` (new to the comparison). UX challenge: a first-time
  reader had to scan five pill badges and a settings row to learn whether the app was safe, acting by itself, or needed
  them. Added an "At a glance" section (`buildGlance`/`renderGlance` in `app.js`, plus `/api/risk/policy` in the refresh):
  plain-words OK/Note/ACTION lines for paper mode, kill switch, fictional data, automatic entries, quote verification,
  risk limits, last-cycle errors, stopped loop, thin results and unmeasurable open P&L. Missing data reads as "unknown", not
  "fine". Frontend only; no risk, order, auth, sizing or broker code touched. Weaknesses noted: it only restates data the
  API already had, so it cannot see anything alerter-only (per-account tuning, Mac DB); the 30-trade results gate is still
  not an out-of-sample test. 1 new test (runs `buildGlance` under node; skipped if node is missing); 181 pass. Weekend
  scan: Yahoo still unreachable (HTTP 000); MONDAY_PLAN says so. The Mac copy is a manual git clone: merged code is not
  on the Mac until the owner pulls.

* 2026-11-15 (run 7): Alerter unchanged (`a7a2ca0`); re-read `gex.py` for the formula and caveats. UX challenge: the
  owner asked for net GEX and the dashboard had no market-context view at all. Added `optplat/gex.py` (`net_gex`),
  a `gex` list and `gex_assumptions` in the cycle report, and a dashboard panel with the assumption stated in the
  note. Display only: `propose`, sizing, risk and orders untouched; a GEX failure is logged to `errors` only.
  Weaknesses noted: the platform's chain is a provider sample, so totals are partial (the alerter refuses partial
  results at its row cap; the platform labels instead of refusing); GEX is computed from the symbols the cycle
  scans, so symbols after an early buy are missing; the 4% rate and call+/put- sign are the alerter's assumptions
  copied for comparability. 5 new tests; 180 pass. Weekend scan: Yahoo still unreachable (no response); MONDAY_PLAN
  says so. The Mac copy is a manual git clone: merged code is not on the Mac until the owner pulls.

* 2026-11-15 (run 6): Alerter unchanged (`a7a2ca0`); read `market_breadth.py`. UX challenge: the owner could see
  only the one contract bought (or a skip reason), never what else qualified, so a buy looked arbitrary. The cycle
  report now has `candidates` (top 3 per symbol, best 10 overall, with score/limit/spread/DTE) and the dashboard a
  "Top candidates" panel stating the score is a ranking heuristic, not a probability. Display only: `propose`,
  sizing, risk and orders untouched. Weakness noted: the entry loop stops scanning after `max_new_per_cycle` buys,
  so candidates from later watchlist symbols are not listed (the panel says so); the score is an unvalidated
  formula mixing spread, moneyness and open interest. 1 new test; 175 pass. Weekend scan: Yahoo still refused by the
  egress proxy; MONDAY_PLAN says so. The Mac copy is a manual git clone: merged code is not on the Mac until the
  owner pulls.

* 2026-11-15 (run 5): Alerter unchanged (`a7a2ca0`); read `gex.py`. UX challenge: the dashboard showed
  engine result codes (`NO_PROPOSAL`) with no reason, so the owner could not tell why nothing was bought.
  Added `LiquidTrendStrategy.explain_no_proposal` (counts why each contract failed), a `reason` on
  `NO_PROPOSAL` entries, and a "Why trades were taken or skipped" dashboard panel (text-only DOM). Display only:
  trading logic unchanged. Other challenge: `explain_no_proposal` mirrors the filter order of `propose`, so the
  two can drift; a test pins the counts. Weekend scan: Yahoo still unreachable here, MONDAY_PLAN says so.
  4 new tests; 174 pass. The Mac copy is a manual git clone: merged code does not reach it until the owner pulls.

* 2026-11-15 (run 4): Alerter moved to `a7a2ca0` (three-workspace dashboard redesign: decision desk,
  audit filters, "unknown marks stay unknown", missing session observation never labelled as closed).
  Added a Results panel to the dashboard (UX row 6): sample-gate verdict first, then P&L, win rate, P&L without
  best trade, split-half, unrealized (n/a when any mark is missing), limitations. Text-only DOM, no
  backend change. 1 new test; 170 pass.

* 2026-11-15 (run 3): Alerter moved to `123eed9` (Mac-only durable paper snapshots and closed-market weekend
  reports in `local_reports.py`; read it plus `liquidity.py`). Added `split_half` to `/api/results`: earlier vs
  later half of closed trades, withheld below 30 trades, `consistent=false` when signs differ. Display only.
  3 new tests; 169 pass.

* 2026-11-15 (run 2): Alerter unchanged since `0107246`. Added `summarize_open_positions` and an
  `open_positions` section on `/api/results` (bid marks, fresh verified quotes only, null total on any
  gap). Display only. 4 new tests; 166 pass.

* 2026-11-15: First run. Added `evaluation.py` and `GET /api/results`: closed-trade summary that
  returns no win rate for zero trades, flags samples under 30 trades, shows P&L without the best
  trade, and lists limitations. Display only; no trading behaviour changed.
