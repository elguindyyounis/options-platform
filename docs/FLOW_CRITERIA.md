# What "interesting options flow" means here (owner examples, 2026-11-16)

Research context, not advice and not a signal. Source of the examples: three screenshots the owner supplied from a paid flow
screen (SMH $330P 11/20: volume 65,601 vs open interest 810, about $1.6M premium, 99.5% ask-side, 31% OTM; MU 410P 11/20:
6,181 vs 931; SPCX 124P 11/16: 43,814 vs 107, about $1.7M). Their numbers were not verified by this repo.

## What the radar looks for (`src/optplat/flow.py`, shown in the dashboard and cycle report as `flow`)

* single contract, reported daily volume at least 150 and at least 3x prior-session open interest (EXTREME = 20x with 5,000+ volume,
  or 50x with 1,500+; thresholds copied from the alerter's `unusual_activity.py`);
* large premium (volume x quoted mid x 100, a scale only), short expiry and far out of the money are flagged, not required;
* the same theme in more than one name (e.g. SMH and MU are both semiconductors) is reported as `flow_themes`, with the note
  that correlated names are not independent evidence. The group table is a hand-written assumption in `RELATED_GROUPS`.

## What the free data cannot tell us (so the radar says "not available")

Ask-side share, multi-leg share, whether a trade opened or closed a position, who the buyer was, and true executed premium.
The screenshots show those; a Yahoo chain does not. A big put can be a hedge, a spread leg or a lottery ticket.

## How it fits the current strategy

None of the three examples would be traded by the platform's `liquid-trend` strategy: it wants near-the-money, mid-dated
contracts with open interest of at least 500 and follows the underlying's 20/50-day trend, while these are 10-46% OTM, 3-7 days
to expiry, and (for SPCX) open interest 107. That is deliberate. Making flow a trade trigger would be a strategy and sizing
decision for the owner; until then flow is context only, and the radar never creates an order. An honest test is
backlog items 1-2 (replay and baseline): did flagged names do anything after, against a do-nothing baseline?

## Weekend scan

On Saturdays and Sundays the challenger should run this radar on a free provider if one is reachable, list the top flagged
contracts in `docs/MONDAY_PLAN.md` with data source and as-of time, and say so plainly when no real data is reachable.
