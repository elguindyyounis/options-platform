# Challenges to the platform

Last alerter commit reviewed: 1fc88f18f2875bb115f8264700a9835cebe45c80

## Open challenges

| # | Challenge | Needs owner? | Status |
|---|-----------|--------------|--------|
| 1 | Rejected/unselected candidates are never recorded, so there is no way to tell whether risk or strategy filters help or hurt (alerter shadow cases). Build on the quote recorder (BACKLOG 1). | No | Open |
| 2 | Paper fills assume the order limit/quote is achievable; there is no slippage or fill-probability model in `sim.py`. Results will look better than a real fill. | Maybe (cost model values) | Open |
| 3 | Win rate / P&L printed with no uncertainty. | No | Done 2026-11-14 (`evidence.py`) |
| 4 | Only one strategy and one set of exit thresholds; once more lanes exist, compare many lanes on few trades only with a multiple-comparison warning. | No | Open |
| 5 | Open positions with no observable bid are excluded from totals silently. | No | Partly done: `open_marks_unobservable` count added; equity impact not yet shown. |

## Run log

| Date | Alerter reviewed | Challenged | Changed |
|------|------------------|-----------|---------|
| 2026-11-14 | 1fc88f1 (first review; no earlier commit recorded) | Headline win rate had no sample-size or uncertainty context | Added `evidence.py` (Wilson 95% interval, sample status, tails, concentration) to `/api/report` and dashboard text; 4 new tests + 1 extended |
