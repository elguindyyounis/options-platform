# Challenges to the platform (from the alerter comparison)

Last alerter commit reviewed: 48ccf71

## Open challenges

| # | Challenge | Needs owner? | Status |
|---|-----------|--------------|--------|
| 1 | Win rate shown with no sample-size label or interval | no | Done on branch `agent/2026-11-14-lane-sample-honesty` |
| 2 | Report has no per-lane or per-strategy breakdown; many lanes judged on few trades will look better than they are. Add a lane table with the same evidence labels and a multiple-comparisons note | no | open |
| 3 | Report rows carry no quote-provenance tag (verified vs unverified quote time), as the alerter's rows do | no | open |
| 4 | Sim fills assume a full fill at ask+slippage with no size/spread dependence; a large order on a thin contract fills better than reality. Consider a spread-and-size-aware penalty (changes fill model, so owner should confirm) | yes | open |
| 5 | `closed` list capped at 50 and `list_orders(limit=1000)` silently truncates the closed-trade count after 1000 orders | no | open |
| 6 | Shrinkage-style estimate for any future lane scoring (alerter uses n/(n+12)) | no | open |

## Run log (newest first)

| Date | Branch | Summary |
|------|--------|---------|
| 2026-11-14 | agent/2026-11-14-lane-sample-honesty | First run. docs created. Added `evidence` block (Wilson 95% interval, SAMPLE_TOO_SMALL under 30 trades, open/unmarked positions) to the report and dashboard. Display only. |
