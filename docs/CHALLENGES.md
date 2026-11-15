# Challenges (platform vs. alerter)

Last alerter commit reviewed: `a7a2ca0`

## Open challenges

| # | Challenge | Needs owner? |
|---|---|---|
| 1 | No commissions/fees in paper fills; results look better than reality. Needs a fee model value. | Yes (cost assumption) |
| 2 | Win/loss stats on few trades. Addressed in part: `/api/results` sample gate plus (2026-11-15 run 3) a chronological split-half stability check. Still no true out-of-sample test or baseline comparison (backlog 2). | No |
| 3 | Alerter judges many lanes on few trades; platform has one strategy but no multiple-testing note once variants exist. | No |
| 4 | ~~Open-position losses invisible~~ Addressed 2026-11-15: `/api/results.open_positions` marks to bid with verified fresh quotes; total is null if any position is unmarkable. Still no equity curve or recorded-quote marking. | No |
| 5 | Alerter's day limits (`day_limits.py`) are all OFF until set and say `NOT_CHECKED` when the ledger cannot measure them; platform has no daily loss halt yet (backlog 3, default is a risk decision). | Yes (default value) |
| 6 | **UX:** `/api/results` existed only as JSON, so the dashboard showed a bare win rate with no sample warning (fixed 2026-11-15 run 4: Results panel). Why-skipped in plain words done (run 5: Decisions panel + `explain_no_proposal`). Top candidates done run 6 (cycle report `candidates`, dashboard panel). Still missing from the owner's mock-up: per-account performance/tuning, net GEX, calendar. Net GEX is feasible from the platform's own `ChainRow` iv/OI (run 5 correction) but must be labelled an invented-inventory assumption like the alerter's `gex.py`; the calendar needs a trustworthy event source (owner). Per-account tuning is alerter-only (Mac DB, not visible here). | Partly |

## Run log

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
