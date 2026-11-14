# Comparison: options-platform and options-alerter

Written 2026-11-12 against alerter commit `9210fd8`. The alerter is the ChatGPT-built private repo; this platform is the
Claude-built one. This is a code-reading comparison, not a performance comparison: neither project has produced evidence
of a trading edge, and nothing here should be read as saying one earns more than the other.

**What was read:** the alerter's README, `PRODUCT_DECISION_ARCHITECTURE.md`, `CHANGELOG.md`, `RELIABILITY_AUDIT.md`,
`gex.py`, `unusual_activity.py`, `entry_quality.py`, `liquidity.py`, `risk.py`, `sizing.py`, `strategy_lanes.py`,
`intraday_strategy.py`, `exit_decisions.py`, `feedback.py`, `adaptive.py`, `agent_lab.py`, `research_foundations.py`,
`daily_review.py`, two agent skill files and the CI workflow. **Not read:** `agents.py`, `core.py`, `storage.py`,
`server.py`, `data_sources.py`, the other skill files, and its tests (none were run). Claims about those are not made.

## Side by side

| Area | options-alerter | options-platform | Who looks stronger, and why |
| --- | --- | --- | --- |
| Unusual option activity | Volume and OI thresholds, no aggressor, no open/close inference, no history | Same thresholds plus buy/sell inference from the last print against bid/ask, open/close inference from OI changes, a persistence history table, follow-up reads | Platform: it adds three kinds of evidence. All of it is still inference from delayed free data. |
| Universe and breadth | Per-symbol scans; no market-wide heat map found | 200 names in 19 sectors, heat map, sentiment, sector caps | Platform |
| Modeled gamma exposure (GEX) | Black-Scholes gamma, 0 to 45 DTE, refuses truncated or biased chains, dealer-sign convention stated as an assumption | None | Alerter. Port candidate (backlog). |
| Entry quality gates | Strict: spread ≤15% of ask, volume ≥20, OI ≥100, size ≤10% of volume and OI, per-symbol and basket caps | Per-lane spread and OI limits; size recorded against volume and OI and tagged afterwards, not gated | Alerter is stricter. The platform's lanes are deliberately looser (owner asked for experiments), but they tag what the alerter would block. |
| Liquidity tiers and exit stress | PREFERRED/WATCH/THIN, plus an extra exit concession for wide spreads and large size | Now ported (`liquidity.py`): tier and stressed exit in every post-mortem, plus an `EXIT_STRESS_FLIPS_RESULT` tag | Equal after this change |
| Simulated trading that actually runs | Four lanes; three are shadow standby or data blocked with automatic orders off. The intraday study is a 3-minute stock proxy, not option P&L. Its own audit (2026-11-10) found 12 positions open and none closed | Five option lanes with automatic simulated entries and exits, fees, stops, targets, stacking | Platform runs more experiments. Whether any is profitable is unknown. |
| Post-mortems on losses | Decision-feedback journal with drivers; a daily review | Rule-based tags per closed trade, a digest, and a minimum of 5 trades before a cause counts as a pattern | Roughly equal; different shape |
| Counterfactuals (rejected and unselected contracts) | Yes: samples scored, rejected and unselected contracts and checks 1, 7 and 30 days later at ask in, bid out | None. Only taken trades are reviewed. | Alerter. Highest-value gap (backlog item 1). |
| Learning from outcomes | Cohort calibration, capped at ±7 score points, off below 5 real trades, shrunk toward neutral, never trained on demo data | Digest only; nothing feeds back automatically | Alerter has a bounded feedback loop. Risk: a few trades can steer it, so keep the cap and the minimum. |
| Exit research | Deterministic shadow exits, optional local model, hard stop/target/hold always win | Fixed premium stop/target/time rules per lane | Alerter explores more. Its shadow exits are hypotheses; none validated. |
| Safety posture | Fail-closed risk engine, skeptic/CIO veto, atomic admission, refuses to buy without exits | Fail-closed `RiskPolicy`, order state machine, `OrderManager` refuses non-paper adapters; research lanes have no order path (AST-tested) | Both strong. Different designs. |
| Research honesty | `research_foundations.py` records the source and validation status of each signal, cites overfitting papers | Limitations strings per lane, "paper proves nothing" throughout | Alerter documents signal provenance better. Port candidate (docs). |
| Operations | launchd deployment with rollback, reliability audit, CI that runs a stock-proxy replay | CI on tests; run script | Alerter |
| Remote and always-on | Mac only; says an offline Mac cannot report its own outage | Same limitation | Equal |

## Where the platform may be wrong

These are challenges raised by reading the alerter. None is proven.

1. **Paper exits were too friendly.** Lanes sold at the bid with no allowance for size. The alerter charges extra when
   the spread is wide or the size is large. With stacking and bigger sizes, this matters more here. *Addressed in this change
   for the post-mortem view; the lane P&L itself still uses the bid, so headline results remain optimistic.*
2. **Unusual-activity signals have no scoreboard.** The platform labels contracts but never checks later whether the
   labelled ones did better than the unlabelled. The alerter's counterfactual journal is the pattern to copy.
3. **Many lanes means many chances to look good by luck.** Five lanes with different settings, judged on small samples,
   is the multiple-comparisons trap the alerter cites. The digest's 5-trade minimum is a floor, not a defence.
4. **No frozen baseline.** Lanes are compared with each other, not with a rule that never changes.
5. **Buy/sell and open/close labels are inferred** from one delayed print and a daily OI number. Treat them as hints.

## Ported in this change

* `src/optplat/liquidity.py`: tier and stressed-exit functions (fail-closed: missing data is THIN and costs the maximum).
* Post-mortems now carry `liquidity_tier`, `stress_net_pct`, `stress_concession_pct` and the `EXIT_STRESS_FLIPS_RESULT` tag.
* No risk limit, lane size or default was changed. Tests: `tests/test_liquidity.py`.

## Not ported, and why

* **Net GEX.** Needs gamma per contract and a dealer-positioning convention that is an assumption. Worth doing as a
  display-only research field, in its own change.
* **Counterfactual journal.** Needs a new table and a daily job that revisits contracts; too large for this change.
* **Cohort calibration.** Would change which trades lanes take. Wait until there are enough closed trades to calibrate on.
* **Strict entry gates.** Applying them would shrink the experiments the owner asked for. The post-mortem tags show what
  they would have caught.
* **Anything about the alerter's council, sizing or goal tracker.** Not read closely enough to judge.

## Added 2026-11-13 (alerter `1fc88f1`): `core.py` and `agents.py`

Since the first review the alerter changed only CI and preflight scripts. Newly read, code only (tests not run):

* **Learning can only tighten.** `research_case` lets adaptive scores and per-agent memory make an approval more
  conservative, never upgrade an ineligible one or reverse a veto. A peer group with 8+ trades, mean return at or below
  -30% and win rate at or below 25% turns a PASS into a stricter hold. The platform has no feedback loop yet; if one is added,
  copy the "tighten only" and minimum-sample rules.
* **A local model may only add caution.** `ollama_reasoning` accepts only localhost endpoints, treats headlines as
  untrusted, and can add a veto but never remove one.
* **Hard skeptic limits** (spread over 35%, no volume, invalid quote, unrecognised source) are deterministic and sit apart
  from score, so a high score cannot buy past them.
* Its council labels unusual volume "cannot establish who bought or sold". The platform goes further and infers side and
  open/close; challenge 7 notes that the second inference can span several sessions.
* `data_sources.py` read 2026-11-13: free yfinance chains only; every candidate carries `opening_trade_verified` and `trade_aggressor_verified` set to False; limitations text says download time is not market time; net GEX is refused (not shown partial) when the near-dated chain exceeds its row cap or a side is missing; held-contract quotes that cannot be found are reported as missing, never replaced. Underlying bars missing means research only, no entries.
* Still unread: `server.py` (partly read 2026-11-14, see below).

## Added 2026-11-13 (alerter `1fc88f1`, second run): `storage.py`

Code only, tests not run. A 413-line SQLite store: WAL, `busy_timeout`, `foreign_keys=ON`, JSON payload columns, candidates,
orders, positions, events, audit and a `trade_journal` table.

* Its `trade_journal` stores the exit quote's timestamp (`exit_quote_at`) next to the exit price, so a result can be checked for
  how stale the price it was marked on was. The platform stores fill times but not the age of the quote an exit used; worth a
  future display-only field.
* Journal rows are written once at entry and updated once at exit (`UPDATE ... WHERE position_id=?` with a changed-row check),
  the same close-only-once pattern as this platform's `lane_close`.
* Nothing found that the platform lacks in safety terms.

## Added 2026-11-14 (alerter `1fc88f1`, unchanged): `server.py` (autopilot and readiness)

Code only, tests not run. Read `run_autopilot_for_symbol` and `automation_readiness`.

* New entries are refused in a fixed order: auto-paper off, exits automation off, scan schedulers off, **held positions with
  unreliable marks** (`unreliable_valuation_count`), session closed, kill switch. Existing positions are untouched.
* `automation_readiness` blocks on stale or failed held quotes, missing or invalid quotes, and held bid/ask spreads over 35%.
  It always reports `quote_time_verified: False` and says freshness is download time.
* Candidate screening uses a three-day cooldown after a simulated stop, and an "adjusted score" from its own calibration.
* The platform's `report()` reported unobservable open marks per row but had no total, so a sum of the open rows could look
  complete when it was not. Challenge 9 (display only) adds the counts. Whether new entries should pause while held marks are
  unreliable (as the alerter does) changes what the platform trades, so it is left for the owner.
* Still unread: the HTTP handlers and `scheduled_scan_loop` in `server.py`, other `agent_skills`.

## Added 2026-11-14 (alerter `1fc88f1`, second run): `paper_engine.py` and two skill files

Code only, tests not run. The alerter's exit manager is 72 lines.

* A failed quote fetch for a held contract is recorded as `UNAVAILABLE`/`UNOBSERVABLE` monitoring failure, never as a HOLD thesis.
  The platform reports unobservable marks per row and (since challenge 9) in a count; it does not stop trading because of them.
* Every automatic close audits an exit-liquidity-stress scenario beside the paper close. The platform computes the stressed exit in
  post-mortems and lane summaries but does not write it as a separate audit event at close time.
* Fixed exits are described as a frozen comparator; model exits are shadow-only unless opted in. The platform's frozen baseline lane
  (challenge 3) plays the same role for entries.
* `position-sizing` and `skeptic-red-team` skill texts require a forward held-out comparison against the unchanged prior version
  before saying anything is better. The platform's provenance page (`SIGNAL_PROVENANCE.md`) adopts that standard.
* Still unread: the HTTP handlers and `scheduled_scan_loop` in `server.py`, and the other five skill files.

## Added 2026-11-14 (alerter `1fc88f1`, third run): `technical-options` and `entry-strategist` skill files

Text only. Both are the same template as the two read earlier: same five-step review, same safety paragraph (no broker orders, a skill cannot
override the Skeptic veto, CIO rejection, quote validation or paper caps, and a forward held-out comparison is needed before calling a
version better). Only the one-line role goal differs. The alerter's `entry-strategist` asks for fresh quote checks and no market-order
assumptions; the platform already prices entries at the ask and exits at the bid.

* A weakness found on the platform side: lane summaries summed `unrealized_pnl` with an unmarked open trade counted as 0. Fixed as a count.
* Read 2026-11-14 (run 4): `portfolio-cio`, `news-flow`, `market-sentiment` skills are the same template. Still unread: the HTTP handlers and `scheduled_scan_loop` in `server.py`.

## Added 2026-11-14 (alerter `1fc88f1`, run 5): `entry_quality.py` and `feedback.py`

Code only, tests not run.

* `entry_quality.py` is a strict gate on real-source entries: spread over 15% of ask, volume under 20, open interest under 100, quantity
  over 10% of volume or of open interest, DTE outside 7 to 730, strike too far from spot (30/40/60% by horizon), per-symbol and basket caps.
  "No score or model may waive these gates." The platform's lanes do not refuse oversized entries (owner's choice), so run 5 only
  *reports* results split by that 10%/10% yardstick (challenge 11).
* `feedback.py` marks rejected and unselected contracts at 1, 7 and 30 days using ask-plus-slippage in and bid-minus-slippage out, requires
  the later quote to be at least 12 hours newer, and leaves unmatched cases as `NO_DATA`, never a gain or loss. Its summaries need 5+ cases
  before saying anything and always add "do not assume the original veto was mistaken". This is the shape the platform's counterfactual
  journal (challenge 1) should keep.
* A weakness found on the platform side: two unrelated functions are both called `liquidity_tier` (challenge 12).
* Still unread: the HTTP handlers and `scheduled_scan_loop` in `server.py`, `adaptive.py`, `exit_decisions.py`, `daily_review.py`.

## Added 2026-11-14 (alerter `1fc88f1`, run 6): `server.py` HTTP handlers

Code only, tests not run. Without a token it serves loopback only and checks the `Host` header (DNS rebinding). With a token it compares
`X-Admin-Token` using `hmac.compare_digest`; a server bound off loopback refuses to start with a token under 24 characters. POSTs must be
same-origin (`Origin` equals `Host`), must not be `Sec-Fetch-Site: cross-site`, and must be `application/json`, token or not. The
platform has the Host allow-list and token; whether it has the origin and content-type checks is open (challenge 13, owner decision).
Still unread: `scheduled_scan_loop`, `adaptive.py`, `exit_decisions.py`, `daily_review.py`.
