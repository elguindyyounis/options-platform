# Shared IBKR research data (owner request, November 26, 2026)

`OPTPLAT_DATA=ibkr` selects `IBKRDataProvider`. It consumes one shared
authenticated service at 127.0.0.1:8791, maintained in Options Alerter's
`ibkr_marketdata.py`; it opens no TWS connection and implements no broker
orders. The broker remains `sim`. The existing TWS adapter skeleton is intact.
No runtime dependencies were added. Install the service from a reviewed stable
Alerter release using its `deploy/install_marketdata.py`, reusing the existing
`~/.ibkr-data-env`. Both consumers read the same mode-600 local token file;
tokens and account identifiers never enter this repository or health output.

Snapshots use identical timestamped shared records for identical request
parameters within the service's ten-second cache window. They retain the oldest
included BBO receipt time, never verify exchange time, and exclude stale,
delayed, frozen, closed-market, disconnected and missing rows. Only live-mode
but **unverified** observations reach research. Option last prices are metadata,
not fills. The source name explicitly says `ibkr-shared-research-only`.

All simulated option fills remain blocked: verified-time risk checks are forced
on for this provider, legacy permissive policy settings cannot bypass IBKR's
unverified-time veto, held executable quotes are withheld, and the separate
experimental option selector refuses unverified IBKR snapshots. No position,
database, risk ceiling, strategy promotion or entry/exit threshold is changed.
History supports daily and five-minute stock bars; it is not option-price
history. Open interest is not depth or opening-buy evidence. The service's
24-row near-ATM chain sample is not full-chain dealer GEX or market-wide flow.

Run the complete `python -m pytest -q` suite and browser syntax check before
pushing. The owner explicitly authorized read-only data integration in this
request, superseding the older broker-data implementation block; it does not
authorize live orders or merging this repository. Submit a PR for human review.
The currently installed Claude app is not changed by this PR. To activate only
after human merge and deployment, set `OPTPLAT_DATA=ibkr` in its private config.
Removing that explicit setting restores the prior provider selection.

Observed Mac audit: installed stable/main `2ade38de9c494a5eff67eb2ba307b6cf0716fae2`,
local port 8800, PAPER mode, runner healthy. Local database read-only counts:
1,245 market snapshots, 1,361,621 quote records, 35 shadow follows and **zero
shadow points** at audit time. The Phase 1 research gate is not established;
no after-cost strategy advantage or champion/challenger winner can be claimed.
Connection probes of the shared service returned stock bars and option
BBO/OI/IV/Greeks; source option BBO exchange time remains unverified.
