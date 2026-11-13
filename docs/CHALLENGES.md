# Challenges to the platform

Last alerter commit reviewed: `9210fd8`

## Open challenges
| # | Challenge | Needs owner? |
|---|-----------|--------------|
| 1 | Risk engine has no order-size vs volume/open-interest participation check (alerter caps at 10%). Adding it tightens risk but is a policy change. | Yes, propose in PR |
| 2 | No counterfactual tracking of rejected proposals (alerter's `feedback.py`). Needs the quote recorder (BACKLOG 1) first. | No, after recorder |
| 3 | `/api/report` reads only the latest 1000 orders; older trades silently drop out of the sample. | No |
| 4 | Exit trigger uses bid, but fill is bid minus slippage, so take-profit/stop-loss P&L is slightly flattering vs the realized fill. Display-only fix possible. | No |
| 5 | Quote times are unverified for Yahoo data; results should carry that label everywhere. | No |

## Resolved
* Win rate shown for tiny samples as if meaningful (1 win = "100%"). Fixed 2026-11-13: report now carries a 95% Wilson interval and an INSUFFICIENT_SAMPLE verdict below 30 closed trades.

## Run log
| Date | Alerter commit | Challenged | Changed |
|------|----------------|------------|---------|
| 2026-11-13 | `9210fd8` (first review) | Win rate with no sample-size context | `evidence.py`, report fields, dashboard text, tests |
