# Challenges (platform vs. alerter)

Last alerter commit reviewed: `123eed9`

## Open challenges

| # | Challenge | Needs owner? |
|---|---|---|
| 1 | No commissions/fees in paper fills; results look better than reality. Needs a fee model value. | Yes (cost assumption) |
| 2 | Win/loss stats on few trades. Addressed in part: `/api/results` sample gate plus (2026-11-15 run 3) a chronological split-half stability check. Still no true out-of-sample test or baseline comparison (backlog 2). | No |
| 3 | Alerter judges many lanes on few trades; platform has one strategy but no multiple-testing note once variants exist. | No |
| 4 | ~~Open-position losses invisible~~ Addressed 2026-11-15: `/api/results.open_positions` marks to bid with verified fresh quotes; total is null if any position is unmarkable. Still no equity curve or recorded-quote marking. | No |
| 5 | Alerter's day limits (`day_limits.py`) are all OFF until set and say `NOT_CHECKED` when the ledger cannot measure them; platform has no daily loss halt yet (backlog 3, default is a risk decision). | Yes (default value) |

## Run log

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
