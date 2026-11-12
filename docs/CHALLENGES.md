# Challenges to the platform

Last alerter commit reviewed: 9210fd8a16b10fb622790cc7dd82980c74a6af08

Nothing here claims an edge. Demo data is fictional and proves nothing.

## Open challenges

| # | Challenge | Needs owner? | Status |
|---|-----------|--------------|--------|
| 1 | Sim fills at the limit with no depth/concession: round-trip costs of big or thin orders are understated. | No for display; yes to gate | Display added 2026-11-12 (`liquidity.py`). Gating on participation is a risk-policy change: owner decides. |
| 2 | Review exit-stress scenarios are a heuristic, not fitted to fills. Compare against recorded quotes once the recorder (backlog 1) exists. | No | Open |
| 3 | `note` on orders is `json.dumps(rationale)[:200]`: truncated JSON, unparseable. Store rationale properly. | No | Open |
| 4 | Backtests/replay will judge many parameter combinations on few trades; no minimum-sample or multiple-comparison guard yet (backlog 3 covers a minimum count). | No | Open |
| 5 | Concentration baskets (ETF/growth-tech) as in the alerter. | Yes (risk policy) | Needs owner |
| 6 | Alerter label inference (who bought/sold from volume/OI) vs platform: platform has none; do not add without trade-level data. | Yes (data) | Needs owner |

## Run log

| Date | Alerter commit | Challenge | Change |
|------|----------------|-----------|--------|
| 2026-11-12 | 9210fd8 | #1 liquidity/exit stress | `liquidity.py`: display-only entry review in engine entry report; strategy rationale gains bid/ask |
