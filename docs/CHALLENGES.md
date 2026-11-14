# Challenges to the platform

Maintained by the daily challenger. Results here come from code, tests and fictional demo data only.

Last alerter commit reviewed: `1fc88f1`

## Open challenges

| # | Challenge | Needs owner? | Status |
| --- | --- | --- | --- |
| 1 | **No participation limit in the risk engine.** `size_quantity` sizes by premium only, so a 1% budget on a cheap contract can be many contracts against volume 50 / OI 500 (strategy minimums). The alerter rejects above 10% of volume/OI. Enforcing it changes which trades happen. | Yes (risk policy) | Evidence now displayed; enforcement proposed, not done |
| 2 | **Flat 0.5% slippage in the sim broker** ignores spread and depth, so paper exits look better than a thin book would allow. Exit-stress scenarios are now shown; the sim fill itself is unchanged. | Yes (changes fills) | Partly addressed (display) |
| 3 | **No basket concentration cap.** SPY/QQQ/IWM puts count as separate underlyings. Alerter caps baskets at 3 and 4. | Yes (risk policy) | Open |
| 4 | **Quote recorder / replay / evaluation report** (backlog 1-3) still absent, so every strategy result is unvalidated. | No | Open, in BACKLOG |
| 5 | **Unknown vs zero.** Check that Yahoo rows with missing volume/OI are never coerced to 0 or to "fine" anywhere in `marketdata.py`. | No | Open |
| 6 | **Small samples.** Any future report must show trade counts and refuse to rank on few trades (alerter shows lanes with `data_validated: False`). | No | Open |

## Run log (newest first)

| Date | Branch | What |
| --- | --- | --- |
| 2026-11-14 | `agent/2026-11-14-liquidity-evidence` | First run. Wrote comparison doc. Added display-only `liquidity.py` (participation flags + exit-stress scenarios) to each entry in the cycle report. No change to what trades. |
