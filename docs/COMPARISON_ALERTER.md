# Platform vs. options-alerter

Alerter reviewed up to commit `0107246`. The alerter is the owner's private research app; this
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
