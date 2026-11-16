# Agent log

Append-only. One entry per agent run: date, what changed, what was verified, what was not.


## 2026-11-13: tracker splits flagged contracts by size of open interest (daily challenger)

* Alerter unchanged since `9210fd8`. Read its `storage.py` and `data_sources.py` (notes in `docs/COMPARISON_ALERTER.md`).
* Challenge 7: the tracker's only open-interest split was "under 10" vs "established", so it could not show whether a volume/OI
  flag over a small base behaves differently. Added a display-only `oi_size` feature (Zero, 1 to 9, 10 to 19, 20 to 99,
  100 to 499, 500 or more, Missing), cut where the alerter's score cap (under 20) and entry gate (100) cut. It rides the existing
  group table and the 20-mark minimum before any group becomes a finding. Marks taken earlier show as "Unknown".
* No lane, risk limit, default, order path or auth was touched. 552 tests pass (12 new).
* Not verified: any real result (the tracker has no real marks I can see; the owner's database is on their Mac), the dashboard
  rendering of the new rows in a browser (the table builds groups generically, no JS changed), the alerter's tests.
* Branch is based on `agent/2026-11-13-lane-stress-pnl`, the newest branch holding these docs; `main` does not have them yet.

## 2026-11-13: stressed exit beside the bid exit in lane summaries (daily challenger)

* Alerter unchanged since `9210fd8`. Read its `agents.py` and `core.py` (notes added to `docs/COMPARISON_ALERTER.md`); the
  local model there can only tighten, and thin contracts have score caps. Logged challenge 7 (tiny open interest vs the volume/OI flag).
* Challenge 4: headline lane P&L assumed the bid at exit, which flatters big sizes. `post_mortem` now also stores `stress_net`
  (money). `lane_report` adds `stress_pnl` per closed trade and `stress_trades`, `stress_bid_pnl`, `stress_pnl` to the summary, over
  only the trades that have a stressed figure so both totals cover the same trades. The Options page shows "Realized, harder exit".
  `realized_pnl`, what lanes trade, risk limits and defaults are untouched; share lanes show n/a.
* 540 tests pass (3 added, none changed or removed).
* Not verified: the new tile in a browser; behaviour on the owner's real data (I cannot see their database). The stressed price
  is a pessimistic model from volume, open interest and spread, not a fill. Older trades without a post-mortem are not counted.

## 2026-11-13: readable contracts, one Trades page, options tracker, sector rotation, Research summary, Desk redesign

* Owner asked (voice) for: single stocks and sector rotation, a better UX, contracts shown as "SPY call 751 · Dec 11", every lane's
  trades on the Trades page with an options/shares sort, a tracker for what makes an option unusual, an options agent, and a
  Research page that shows what was learned and whether it is improving. "Spineless decisions" was read as the SPY/QQQ-only decisions.
* Contract names: `contracts.py` and a client-side OCC parser; also fixed days-to-expiry showing "unknown" for padded OCC symbols.
* `GET /api/alltrades` merges the options account, five option lanes, the 10x challenge and both share lanes; the page filters by
  options or shares and by lane and sorts every column. Lane trades open inline, account trades open the order trail.
* `tracker.py`: every flagged contract is re-read on later scans and marked at 1, 3 and 7 trading days (ask in, bid out, plus the
  underlying's move in the helpful direction), grouped by what was known at the flag. Groups under 20 marks are labelled too few.
  `GET /api/tracker`, a Tracker page listing the exact criteria for "unusual". This is challenge 1 in `docs/CHALLENGES.md`, in part.
* Options agent: the committee already had agents; what was missing was one that reads flagged flow on the candidate's own name.
  Added `flow`, which can only OPPOSE (low confidence, starts at a quarter of normal weight). When flow agrees it records
  `would_support` and does nothing, so it cannot add conviction or loosen entries. Letting it support is left to the owner.
* `rotation.py` and Market, Sector rotation: each sector's share of dollar volume across days from stored scans. Needs scans from
  two or more trading days. Controls got a sector picker that fills the watchlist box with a sector's four most traded names;
  nothing is saved until Save settings. The 20-name cap, risk limits and defaults (SPY, QQQ) are unchanged.
* `learning.py` and the Research page: older half against newer half of closed trades (no verdict under 20 each), lessons labelled
  pattern, anecdote or lead, agent weights, a timeline. `GET /api/learning`.
* Owner asked for restart-on-update. `watch.sh` follows the current branch (fast-forward only, refuses with local edits or local commits,
  never touches main unless you are on it), restarts the platform and keeps one dashboard token in `.venv/.optplat_token` (mode 600) so
  the open page stays connected. `run.sh` now lets `OPTPLAT_OPEN_BROWSER` be overridden so restarts do not open new tabs. 4 tests use
  throwaway git repos and a fake run command. Not verified on macOS or with the real `./run.sh`. Trade-off: pushed code runs unreviewed.
* Desk redesigned: large account value, open positions as cards with a stop-to-target ladder, a decisions feed.
* Owner follow-up: the Desk now has an "All accounts and lanes" block (options account, every option lane, the 10x challenge, both share lanes,
  and a total) so lane results are visible on the front page. It reuses `/api/alltrades`; no new backend. The total adds simulated dollars from
  lanes with different sizes and is labelled as not an account balance. Checked in headless Chromium on demo data at desktop and phone width.
* 537 tests pass. Checked in headless Chromium on fictional demo data only (dark, phone width, every page, no script errors).
  I updated one existing test, the nav list, because a Tracker page was added; no test was weakened or removed.
* Not verified: any of this on the owner's Mac or live Yahoo data; the tracker and rotation need several real trading days to
  show anything; single stocks have not been run through the engine (earnings handling is the events agent's existing behaviour).

## 2026-11-14: folded the open branches into agent/integration (owner present)

* Merged `agent/2026-11-14-gex-display` (PR #4; carries the daily-challenger, tracker, rotation and Desk work) and
  `agent/2026-11-13-reliability-and-ports` (adds `watch.sh`) into `agent/integration`. Conflicts were docs only; I kept both sides.
* Not merged: PR #3 (`agent/2026-11-10-quote-recorder`). It is an older copy of the recorder that integration already has
  in a newer form, and it conflicts in `engine.py`, `store.py` and tests. Owner may close it.
* Nothing was merged into `main`, per the earlier owner decision and CLAUDE.md rule 6.
* Verified: 560 tests pass. Not verified: `watch.sh` on the owner's Mac.

## 2026-11-14: recorded the owner's standing direction (owner present, docs only)

* Added "Standing direction: research first, broker last" and a broker-readiness checklist to `docs/BACKLOG.md`.
  Docs only: no code, risk policy or tests changed. Not verified: nothing to verify beyond the text.

## 2026-11-13: frozen baseline lane (challenge 3, scheduled run)

* Added `FROZEN_BASELINE` in `optionlanes.py`: a lane written out in full (not derived from `SHORT_BASE`) so tuning
  the base lane cannot move the yardstick. `FROZEN_FINGERPRINT` and a test pin its settings; any change needs the owner
  and a new lane id. Simulated trades only: no orders, no risk policy change. Lane count is now six (two tests updated
  from 5 to 6; no assertion loosened).
* Skipped because other `agent/2026-11-13-*` branches already hold them (not in integration yet): counterfactual journal,
  stressed lane P&L, signal provenance, GEX labels. Those may conflict with this commit on `optionlanes.py`/docs.
* Verified: 498 tests pass. Not verified: the lane running against live Yahoo data; it duplicates the base lane's signals, so
  until the base is tuned the two will look alike.

## 2026-11-13: the 10x challenge account

* Owner asked for an aggressive paper account (10x in a month, restartable, critical of every trade). Built it as a separate
  research account (`challenge.py`, lane `challenge-10x`) so the real account's `RiskPolicy` is untouched: $10,000 start, 25% of
  equity per trade, EMA9/VWAP calls and puts up to a week out, ends on 10x, down 90%, 30 days or a manual restart, then starts a
  new attempt. Every attempt is kept in `challenge:history`; the report states the success rate across ALL attempts, because
  restarting until one works is selection, not evidence.
* The critic (`_review`) can refuse a trade (thin contract, exit that would cost over 12% extra under stress, over 60% of equity at
  risk, a third trade right after three losses, chasing a name stopped out today), cuts size to 10% of volume and 15% of open
  interest, and stores objections, thesis and what would prove it wrong with every trade. Base lanes got a no-op `_review` hook.
* Dashboard: a 10x challenge panel at the top of the Options page; `GET /api/challenge`, `POST /api/challenge/restart`.
* 497 tests pass; panel checked in headless Chromium on fictional demo data only (dark and phone widths, no script errors).
* Not verified: behaviour on live Yahoo data; whether the critic's thresholds are sensible (they are guesses to be challenged);
  expiry handling for positions held across a challenge end. A 10x target pushes towards long shots, so expect many ruins.

## 2026-11-13: restart recovery, error text, clock warning, side-by-side ports

* Read-only look at the owner's database found: the simulated broker forgot a filled SPY put on restart (equity reset to
  exactly 100,000), scans read 0 chains because the Mac clock ran 7 to 11 s behind quote timestamps (gate limit 5 s), and one
  chain error showed only its type.
* `SimBroker.restore` replays FILLED orders at startup (cash and positions); impossible histories are warned about and skipped.
  `describe_exc` puts the message and file:line in scan and lane errors. The engine status carries `clock` and the dashboard's
  trust panel shows it. `choose_port` lets the platform run beside the alerter and refuses a second copy on the same database.
* No risk limit, tolerance, auth check or default changed. The 5 s clock tolerance is untouched. 484 tests pass.
* Option lanes now save what their last check did, including errors and skip reasons, and the Options page shows it under
  "Last check". The live database had no record of why the swing and flow option lanes made no trades.
* Not verified: any of this on the owner's Mac or live Yahoo data; resting (unfilled) orders are not restored; why the owner could
  not open both apps (ports never clashed by default, so the cause is unconfirmed).

## 2026-11-12: alerter comparison and liquidity stress

* Compared the owner's `options-alerter` repo with this platform (`docs/COMPARISON_ALERTER.md`) and started
  `docs/CHALLENGES.md`, the log for a daily challenger agent.
* Ported liquidity tiers and an exit-stress scenario (`src/optplat/liquidity.py`) into post-mortems, with a new
  `EXIT_STRESS_FLIPS_RESULT` tag. No risk limit, budget or default was changed. 472 tests pass.
* Not verified: the alerter's own tests (not run), the alerter modules listed as unread in the comparison, and
  any live Yahoo data. Lane P&L still uses the bid; only the post-mortem shows the stressed view.

## 2026-11-12: bigger sizes and stacking in the option lanes (owner request)

* Owner asked for larger size caps and for positions to stack on one name. In the option lanes only: aggressive lanes now
  risk $5,000 to $10,000 of premium per trade with 15 to 20 open, may hold up to 3 positions in one name (`stack="any"`),
  and the flow lane doubles size on a very thin contract and adds a second position only to a winner. Base lanes grew
  modestly and stay as the control. Each trade records its size against the contract's volume and open interest, and an
  oversized or stacked trade is tagged in its post-mortem so the digest shows whether stacking and size pay.
* NOT changed: the real paper account's `RiskPolicy` (`max_same_underlying_side` = 2, `max_position_pct`,
  `max_total_premium_pct`). Those are the "already holding a position: concentration limit" rejections, and CLAUDE.md
  reserves them for the owner. The share benchmark lanes are also unchanged.
* Verified: 466 tests. Not verified: any claim that bigger or stacked trades do better; fills at this size are optimistic.

## 2026-11-12: options-first research lanes and scanner v2 (human-directed session)

* Owner asked for options-heavy, more experimental, automated research. Added: `universe.py` (200 names, 19 sectors),
  scanner v2 (open interest under 10 flagged at 100+ contracts, weeklies, `ChainRow.last`, `trade_side`, `unusual_history`
  table, `compare_with_prior`, `follow_ups`, heat map, sentiment), `optionlanes.py` (five lanes), `postmortem.py`, a
  per-sector cap on the share swing lane, `snapshot_window` on providers, `/api/optlanes`, an Options dashboard page and
  Market tabs (heat map, did it stick).
* Safety: the option lanes import nothing from orders, broker, risk or engine (a test checks it); `RiskPolicy`, its 7-day
  minimum and every default are untouched; lanes default off. Aggressive variants only loosen the lanes' own rules.
* Verified: 457 tests; headless Chromium on demo data at 1280 and 390 px, light and dark, no overflow or console errors.
* Not verified: live Yahoo `lastPrice` semantics, `snapshot_window` and chain-read rate limits for ~60 chains per scan,
  the 200-name daily download, whether open interest updates promptly, after-hours quotes (the quality gate drops zero-ask
  rows, so scans and lanes only work while quotes exist). Buy/sell and open/close reads are inference only.
* Owner decisions: raising real risk limits or caps, promoting anything, licensed data, a real broker.

## 2026-11-12: "it only did one trade" (owner's real run, read from their database copy with their permission)

* The owner's real database showed the swing lane working on real Yahoo data: 72 of 74 names judged on the 2026-11-11
  bar and 2 on 2026-11-10, with 2 open trades (UNH, PFE, both from the 11-10 bar). The short-term lane made 4 real-data
  trades on 11-11 (QQQ, NVDA and TSLA closed on target or VWAP, SPY closed flat by the close). So the live lanes are
  trading; the rule is selective, about 1 to 2 signals a day across 74 names.
* The replay's "one trade" output was not seen. A likely cause: `daily_bars(..., months=12)` sent Yahoo the period
  `12mo`, which is not a documented value (`6mo` and `2mo` had worked live). It now maps long spans to `1y` or `2y`.
  The replay also prints how many funds had data and how many bars each had, so a thin result explains itself.
* Separate finding in the same database: the latest scan read 0 option chains because every one was rejected by the
  data-quality gate (NVDA, QQQ, SPY and others). It ran about 06:57 UTC, with the market closed, which would explain
  empty quotes, but that is unconfirmed. Worth re-checking during market hours.
* Tests: 387 pass (2 new). Not verified: the replay on real bars.

## 2026-11-11: swing replay (owner agreed the rule settings and asked for simulated trades now)

* The owner approved the swing settings as written. This sandbox cannot reach Yahoo (the request returns nothing and
  yfinance is not installed), so there is no real market data here and no real-data paper trades could be made from
  this session. Trades on real data are made by the owner's own run (`./run.sh yahoo --loop`, swing lane on).
* To give history immediately instead of waiting days, `swing_replay.py` runs the same `SwingLane.step` day by day over
  past daily bars in a throwaway in-memory store. Each day sees only bars up to that day. Run it with
  `.venv/bin/python -m optplat.swing_replay --data yahoo --months 12`. It covers funds only (no historical earnings
  dates, so single stocks would be contaminated), enters at the close, models no gaps, and prints the same-window
  buy-and-hold average for comparison. It never writes to the real database.
* Tests: 385 pass (4 new: funds only, no look-ahead, determinism, demo run and text output).
* Verified only on fictional demo data (78 invented trades, which mean nothing). Not verified on real bars.
* A good-looking replay still proves nothing: the same bars were used to look at the outcome and the rule is untested out of sample.

## 2026-11-11: swing research lane (owner present, "start with swing trading")

* `swing.py`: a research experiment on DAILY bars of the 74-name scan universe. Buy a pullback inside an uptrend
  (20-day average above the 50-day, close above the 50-day, RSI(14) at or below 45 on one of the last 3 days, then
  RSI rising and a higher close, skipping a day that moved more than 5%). Exit at a stop (2.5 daily standard
  deviations, clamped 3% to 10%), a 1.5R target, a close below the 50-day average, or after 10 trading days. Simulated
  share trades in the same separate ledger as the short-term lane (`lane_trades`); no orders, no broker, no change to
  the options account or the risk policy. Off by default (`swing_enabled`); `./run.sh` switches it on.
* Each trade stores its own stop, target and time limit when it opens, so editing a setting never moves an open trade.
  Single stocks need a known earnings date with none inside the hold plus 14 days (unknown blocks the entry); funds are
  exempt. A failed or empty feed means no entry. It runs at most hourly and judges each daily bar once.
* `daily_bars(symbols, months=2)` gained a months argument (the scanner's default is unchanged). The shared ledger
  report moved to `shortterm.lane_report`.
* Dashboard: Swing page next to Short-term, one shared renderer, a Controls switch, `/api/swing` and
  `POST /api/swing/step` (409 while off).
* Tests: 381 pass (15 new for swing, including each exit reason, the throttle, the earnings rules and the API).
* Not verified: Yahoo 6-month daily bars for 74 names in one call, and Yahoo earnings dates, against the live network.
  Entries are simulated at the latest close, not the next open, and gaps are not modelled. The rule settings were
  chosen before any result; owner, please review them. Nothing here is evidence of an edge.

## 2026-11-11: short-term research lane (owner present, direction given in chat)

* Owner direction: a long-term portfolio plus a short-term day-trading strategy. The long-term book is the existing
  options engine. The short-term lane is a separate research experiment, `shortterm.py`: an EMA9 versus session VWAP
  rule on 5-minute bars of SPY, QQQ, IWM, AAPL, NVDA and TSLA, long only, simulated share trades on the underlying in
  its own ledger (`lane_trades`). It places no orders, uses no broker and does not touch the risk policy or the
  options account. It is off by default (`shortterm_enabled`); `./run.sh` switches it on.
* Why shares and not options: the risk policy keeps entries at 7 or more days to expiry and the free feed is delayed
  about 15 minutes, so a real options day trade is not possible. Changing either is an owner decision.
* The rule parameters (10:00 to 15:00 ET entries, 0.5% stop, 1.0% target, VWAP exit, flat by 15:45, $1,000 simulated
  size, 3 open, 0.05% slippage each way) were fixed before any result and are research settings, not risk limits.
  Owner: please review them. Unknown, stale or too little data means no entry.
* Dashboard: new Short-term page (rule, limits, simulated trades, phone cards) and a Controls switch. API:
  `/api/shortterm`, `POST /api/shortterm/step` (409 while off).
* Tests: 366 pass (12 new: indicators, one entry per signal, window, stale and failing feeds, exits, carried-over
  trades, the open cap, report maths, off-by-default, API).
* Not verified: Yahoo intraday bars live (`yf.download(..., interval="5m")` is untested against the network), and
  nothing here is evidence of an edge. The demo run used invented prices.
* Skill repos the owner named: `claude-trading-skills` and `day-trader-skill` were read but NOT installed. The
  second contains `trader-broker`, an Alpaca order path, which this repo's rules reserve for the owner. The auto-mode
  classifier also blocked copying skills into `~/.claude/skills`. Nothing was installed.

## 2026-11-11: dashboard v2, with a trade blotter and trade files (owner present)

* The dashboard is now six pages behind a left rail (a bottom bar on phones): Desk, Trades, Market, Agents,
  Research, Controls. Routing uses the URL fragment, and the `#token=` fragment is still read first and scrubbed.
* Trades page: every trade from `/api/trades` in a filterable, searchable, sortable blotter (cards on phones).
  Selecting a row opens a trade file: result, what was bought and sold, the entry reasoning, how each agent voted
  (with the skeptic's objections), why it exited in plain words, and the order audit trail. Esc closes it, focus
  is trapped while it is open and returned to the row afterwards.
* Market page shows the scan: most active names, unusual options activity (filterable to what the rules allow
  it to review) and option volume by name, with the limitations in a disclosure. Agents page shows the record
  per agent, the latest votes, lessons and weight changes. Scan interval is now a control.
* `/api/journal` gained an optional `kind` filter (upper-case letters only, 422 otherwise). No auth change.
* DOM is still built with `textContent` only. All data in the screenshots was fictional demo data.
* Tests: 354 pass (4 new for the pages, safety behaviours of the script, the journal filter and the endpoints the
  page reads). No existing assertion was changed.
* Verified in headless Chromium at 1280 and 390 px, light and dark: no JS errors, no horizontal overflow on any
  page, drawer open/close/focus, filters and search. Not verified: Safari, a real screen reader, the live Yahoo
  scan (the demo provider has no unusual contracts, so the unusual table was checked with two invented rows).
* Owner direction noted: a long-term portfolio plus a short-term day-trading lane. See backlog item 3.

## 2026-11-11: most-active names, unusual options activity and a trade ledger (owner present)

* `scanner.py`: ranks a FIXED universe of about 75 liquid names and funds by dollar volume and relative volume
  (today's partial bar is dropped while the session is open), then reads the option chains of the most active
  and the volume-surge names and flags contracts with volume at least 150 and at least 3x open interest, or at
  least 500 with zero or missing open interest (no ratio is shown then, never infinity). Rules were adapted
  from the owner's options-alerter repo. Contracts are REVIEWABLE (liquidity tier A or B, 7-730 days) or
  OBSERVE_ONLY. It is research context: it places no orders and does not feed the strategy.
* `trades.py` and `/api/trades`: every filled entry is a trade, exits matched oldest first, open quantity marked at
  the bid (None and "unobservable" if there is no valid bid), with the entry rationale, the committee's votes,
  the exit trigger and the audit trail. `/api/scan`, `POST /api/scan/run`. `scan_interval_s` (0 = off, else
  600-86400); `./run.sh` sets 1800.
* Found and fixed by a flaky test: entries and exits with the same timestamp were ordered by random id, so an
  exit could be processed before its entry. Ordering now follows the ledger's recorded sequence.
* From the skills repo (tradermonty/claude-trading-skills, MIT): it has no most-active or unusual-activity skill.
  Most of its screeners need an FMP key, which is an owner decision. Nothing was copied.
* Verified: 350 tests, stable over repeated runs. Not verified: `yf.download` for the daily bars against the live
  Yahoo service (parsing is shaped for yfinance's grouped-ticker frame and is untested live), and Yahoo rate limits
  with about 18 chain reads per scan.
* Not built: feeding scan results into the committee or the watchlist, and recording scan chains for replay.

## 2026-11-11: event and earnings agent (owner present)

* New `events.py` and an `events` gate in the committee. FOMC decision days for 2026 and 2027 come from
  https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm (read today; the Fed marks 2027 tentative, and
  the code marks those events tentative). Later years are unknown and answer None. Earnings dates come from Yahoo's
  unofficial calendar through yfinance: no key or account, but unofficial and often estimates.
* Rules: a calendar answers a list or None, and None is never "safe". An unknown earnings date for a single stock
  is a hard veto that learning cannot soften. Funds (a listed set including SPY and QQQ) have no earnings. Earnings
  within 5 days is a learnable veto; later earnings inside the option's life, or an FOMC decision today or
  tomorrow, weigh against. The skeptic reports a missing calendar or table gap.
* Consequence to expect: with the default SPY and QQQ watchlist the agent rarely matters. For single stocks, entries
  need a known earnings date, and if Yahoo returns nothing the committee will decline them.
* Verified: 326 tests, including the fail-closed cases and a fake `yfinance`. Not verified: the real Yahoo
  earnings call from this environment (no network to it), or that its dates are right. The 5-day and 1-day
  windows are my experiment parameters.
* Not covered: CPI, jobs data, dividends, index events, news.

## 2026-11-11: agent committee that learns (owner present, direction given in chat)

* Owner direction: agents that analyse, take and size trades, a skeptic that always argues against, and an
  experimental, adaptive loop with no promotion step ("mistakes are fine as long as it learns").
* Built: six deterministic agents (technical, volatility, options-sentiment, execution, exposure, skeptic),
  a committee that combines them, and a learning step. Weights are a pure function of the last 500 journaled
  votes scored at 4 h (SUPPORT is right if the contract's bid rose, OPPOSE if it did not), shrunk toward
  neutral until an agent has about 30 outcomes. The committee's own trust starts at 50% of the allowed size
  and follows its entry hit rate. Rejected candidates are scored too, so it learns without having to trade.
* `committee_mode`: off, shadow (default; records votes only, so the frozen baseline and replays are
  unchanged) or active (`./run.sh` sets it). Active mode can refuse a candidate or take less than the cap.
* Bounds that stay in force: quantity never exceeds `size_quantity` (tested across extreme weights and
  trust), every order still passes the risk gate, data-integrity vetoes are never softened by learning,
  an agent that crashes vetoes, a crashing committee places nothing. Paper only.
* Decisions for the owner to confirm: (1) the options-sentiment agent uses signals that are still
  UNVALIDATED. It starts at weight 0.25 and has to earn influence, instead of waiting for
  `VALIDATED_SIGNALS`. The baseline strategy still cannot use them. (2) "Grow a position" is bounded by the
  risk policy's caps, which I did not touch. Raising a cap is a risk-policy change in `risk.py`.
* Not built: scaling into or out of already-held positions (backlog), news sentiment (needs a data
  source), event calendar (needs a source). All thresholds in `agents.py` are experiment parameters.
* Verified: 315 tests; the dashboard panel in headless Chromium with no page errors. Not verified: any
  learning on real recorded data. It needs days of running before the weights mean anything.

## 2026-11-11: weekly research report (roadmap step 6, owner away)

* New `weekly.py` and `python -m optplat.weekly [--days N] [--fictional] [--out file]`. Opens the
  database read-only, so it cannot trade, register a hypothesis or change a setting. Rule-based, no
  language model. Sections: data trust, paper account, decisions and top risk rejections, 24 h forward
  outcomes of chosen vs passed-over candidates, experiments, and proposed questions.
* Proposals are questions with evidence, never instructions: reliability first; a rejection rule that
  causes more than half of 20+ rejections is flagged for the owner (the text says an agent must not loosen
  it); a ranking question appears only with 30+ matured outcomes in both groups and a 2-point gap.
* Verified: 290 tests pass, including thresholds, the read-only CLI and error paths.
* Not done on purpose: scheduling it. Where and how often it runs is the owner's call. Thresholds for
  proposals are my choice and are only prompts for a human, not trading parameters.

## 2026-11-11: dashboard question audit (roadmap step 5, owner away)

* Every dashboard panel now states the trading question it answers; a test fails on any `<section>`
  without `data-question` (or `data-plumbing` for the connect box). Panels: controls, "can I trust
  this right now" (loop, last cycle and errors, data source, market, recorder counts, 24 h data
  quality, with a verdict line), account and results, open positions (take-profit and stop levels
  at the bid, days to expiry), decisions, orders, experiments (pre-registered hypotheses and their
  status). The duplicated per-cycle table was removed: the decision journal already answers "why".
* New `equity` table, written once per completed cycle only while trading is allowed (no flat overnight
  points), pruned at 90 days or the snapshot retention if longer, and kept apart by fictional/real so a
  made-up curve never mixes with a real one. `/api/equity`, `/api/research/hypotheses`, `equity_summary`.
* Equity chart: one series, no legend, hairline grid, start-equity reference, end label, crosshair
  tooltip (arrow keys work), "show as table", light and dark colours, drawn at the real pixel width so
  text stays readable on a phone. Built with `createElementNS` and `textContent` only.
* The sample-size notice states that fewer than 30 closed trades is not evidence. The chart title says
  nothing about edge, and fictional data is labelled in the tiles and the trust panel.
* Verified: 283 tests pass; page loaded in headless Chromium at 1100 px and 390 px in light and dark
  with no console or page errors and no horizontal overflow; hover tooltip and table toggle exercised.
  Visual check used a fictional demo curve I seeded for the test.
* Not verified: the page against live Yahoo data or in Safari; exit-level columns assume the
  engine's percent thresholds apply to average cost, as `exits.py` does. No risk defaults or exit
  thresholds were changed.

## 2026-11-11: options signals as measured features (roadmap step 4, owner away)

* New `signals.py`: coverage of the sampled chain, liquidity tiers (A/B/C; B is the baseline's own
  filter), volume-to-open-interest and unusual-activity flags (volume at least equal to open interest,
  with minimums; trade direction is unknown and stated), call/put volume and OI ratios (undefined,
  not infinite, when one side is empty), and Black-Scholes GEX (calls positive, puts negative; stated
  as contested; r = 0; rows without IV, open interest or at least 1 day to expiry are skipped and
  counted). GEX is always marked `partial_chain` because Yahoo gives a sample, not the full chain.
* Gate: every result says UNVALIDATED. `VALIDATED_SIGNALS` is empty and `use_signal(name)` raises
  until the owner adds a name. No strategy reads any signal today, so trading behaviour is unchanged.
* `study_signal` measures Spearman rank correlation between a signal and the underlying's next-24h
  move (default) from recorded real snapshots that pass the data-quality gate. Gaps are skipped, not
  stretched. It is descriptive below 100 observations (which overlap, so the effective sample is
  smaller) and never validates anything. CLI `python -m optplat.signals scan|study` is read-only.
  `GET /api/signals/{symbol}` (token required) returns the latest signals.
* 19 new tests including the textbook gamma value (S=K=100, T=1, vol 20% gives 0.019848).
* Not verified: any signal on real data (no multi-week recording yet), and whether Yahoo's volume and
  IV fields are reliable enough for these to mean anything. The coverage numbers will show that.
* Not built: true unusual-options-activity detection needs licensed trade-level data (owner decision).

## 2026-11-11: champion/challenger framework (roadmap step 3, owner away)

* New `research.py` and `python -m optplat.research register|evaluate|list`. Rules enforced in code:
  the baseline (`liquid-trend 0.1.0`, default parameters) is frozen by fingerprint and evaluation
  refuses if it ever moves; a hypothesis (statement, challenger, pass criteria) is stored append-only
  with a content hash, and tampering is detected; a challenger may change strategy parameters only,
  never exits, risk limits or the evaluation criteria; criteria cannot be laxer than 30 closed trades
  total and 10 out of sample, and need a strictly positive improvement; a confirmatory evaluation uses
  only snapshots recorded after registration; exploratory runs on older data can never pass; the first
  time the sample requirements are met the verdict is recorded and returned unchanged on re-runs (no
  optional stopping); every result shows how many hypotheses have been registered, and says
  "PASSED_CRITERIA" is not proof of an edge and promotion is the owner's decision.
* "Shadow mode" is implemented as replay of the same forward-recorded snapshots through challenger and
  baseline, so the comparison is deterministic and places no orders.
* 19 new tests (verdict logic is tested with controlled inputs; one integration run uses a synthetic
  market that gives the baseline ~44 distinct trades). 255 total.
* Not verified: any real hypothesis (needs weeks of recorded data). Passing needs both arms to trade
  enough, which on a 2-symbol watchlist may take a long time.
* For the owner: consider adding to CLAUDE.md that agents must not edit `BASELINE`,
  `BASELINE_FINGERPRINT`, or the criteria floors in `research.py`. I did not edit CLAUDE.md myself.

## 2026-11-11: decision journal and rejected-opportunity tracking (roadmap step 2, owner away)

* New append-only `decisions` table. The engine writes one record for each placed or risk-rejected
  entry, each non-HOLD exit, and each candidate not taken (`NOT_CHOSEN`, `NOT_CHOSEN_SIZE_CAP`,
  `SKIPPED_HELD`, `SKIPPED_COOLDOWN`, `KEY_CONFLICT`), with the strategy rationale and score, risk
  failures, data provenance (source, whether quote times are verified, broker) and stated
  assumptions. Up to 5 candidates per symbol per cycle; identical non-order records are not
  rewritten within an hour. Journaling can never stop a cycle. Records are never edited.
* New `journal.py`: for each entry candidate, the contract's bid at 4h / 24h / 120h after, from the
  first recorded snapshot at or after the horizon that passes the data-quality gate. A gap beyond 25%
  of the horizon, a missing contract or a failed snapshot is `UNOBSERVABLE`; a not-yet-recorded
  horizon is `PENDING`; a zero bid is -100%. Nothing is interpolated. Groups under 30 matured
  candidates are marked descriptive only.
* API: `GET /api/journal`, `GET /api/journal/summary` (both behind the token). Dashboard: new panel
  "Why did it act, or not?" (the question it answers is its heading).
* 17 new tests, 236 total; a headless-browser load of the demo market shows the panel with no JS errors.
* Not verified: any real forward outcomes (needs days of recorded data); the journal's volume on a
  full real session. Overnight and weekend horizons will mostly read UNOBSERVABLE by design.
* Journal rows are not pruned. Reviewer: decide a retention policy once its size is known.

## 2026-11-11: data-quality gate (roadmap step 1, owner away)

* Owner set the direction: a self-improving paper research platform (see BACKLOG "Direction"). Step 1
  is reliability: no misleading data reaches a signal or a decision.
* New `dataquality.py`, applied by the engine to every snapshot before any strategy, exit rule or
  simulated quote sees it. Dropped rows: crossed, zero or non-finite ask/bid, expired, duplicate.
  Whole-snapshot rejects: bad underlying or history, stale (over 900 s) or future-dated, no usable
  rows. Warnings kept and counted: implausible IV (value removed, not corrected), negative
  volume/open interest, spot far from last close, quotes identical for 3+ cycles while the market is
  open. A rejected snapshot behaves like a failed fetch (fails closed). The checks only remove data, so
  they can make the platform trade less, never more. No risk limit or default changed.
* The raw snapshot is still recorded before the gate runs (evidence kept), and replay applies the same
  gate, so replayed decisions match live ones. Issues go to a new `data_issues` table (pruned with the
  snapshot retention) and the dashboard shows a "Data quality, last 24h" line.
* Checked, not changed: held-position quotes already pass `exits.py` validity and 60 s staleness checks.
* 20 new tests, 219 total. Thresholds (900 s age, IV 0-500%, 20% spot gap, 3 frozen cycles) are my
  choices; the owner may want them stricter. Not verified: how often Yahoo data trips these in
  practice. The dashboard line will show it after a real session.
* Roadmap for later steps is in BACKLOG "Direction" and "Next up".

## 2026-11-11: runner health (owner away)

* `Runner` now tracks `last_success_at` (a cycle that returned without raising) and reports
  `seconds_since_success` and `stalled` (running with no good cycle for more than 3 intervals).
  `/api/health` gets `runner: {running, stalled, seconds_since_success}` only; the error text stays in
  the token-protected `/api/engine/status`. Reviewer: `/api/health` is unauthenticated and now also
  reveals loop activity timing; no auth check was changed.
* Dashboard shows `LOOP STALLED: no good cycle for Ns` in red; the last error is in the pill tooltip.
* 7 new tests, 199 total. Not verified: a real stall (for example a hung Yahoo call). A cycle that is
  slow rather than failing will also be flagged once it exceeds 3 intervals, which is intended.
* Skipped on purpose: **daily loss halt**. Its default threshold is a risk-limit decision that
  CLAUDE.md reserves for the owner, so it stays on the backlog for a human to specify.

## 2026-11-11: strategy evaluation report (owner away; backlog item after replay)

* `src/optplat/evaluation.py` + `python -m optplat.evaluate`: replays recorded real snapshots in an
  earlier in-sample and a later out-of-sample segment (fresh account each), and reports closed trades,
  win rate, realized P&L, per-trade expectancy, return, max drawdown, a do-nothing baseline and the
  underlying's buy-and-hold move for context.
* Status is `MEASURED` only with at least 30 closed trades in total and 10 out of sample; otherwise
  `INSUFFICIENT_DATA` (figures marked descriptive only); fictional data is always `FICTIONAL_DATA`.
  The report never says a strategy has an edge and always prints its caveats.
* Safety: the CLI opens the database read-only (new `Store(read_only=True)`, tested), changes no live
  setting, keeps the strict quote-time policy unless `--allow-unverified` is passed (same explicit
  opt-in as live), and needs `--entries` before any trade is simulated.
* Added per-step account equity to `ReplayResult` (included in the fingerprint).
* 14 new tests, 192 total. Not verified: results on a real multi-week recording (none exists yet).
  The default thresholds (30 and 10) are my choice; the owner may want stricter ones.

## 2026-11-11: replay provider (owner away; backlog item 1 after the recorder)

* New `src/optplat/replay.py`: `ReplayDataProvider` serves recorded snapshots as of the replay clock
  and never later; `ReplayClock`; `run_replay(rows, strategy, config, policy)` runs one real engine
  cycle per recorded moment in a throwaway in-memory store with the simulated broker.
* Safety properties, each with a test: no look-ahead (mutation-checked: returning the newest snapshot
  makes 6 tests fail); the strict quote-time policy still applies unless the caller passes the same
  explicit opt-in used live; market hours still apply to real rows; automatic entries stay off unless
  the caller asks; replay can never record snapshots again or touch the source database; real and
  fictional rows are never mixed; an empty input is an error.
* Reproducibility: two replays of the same rows give the same `fingerprint()` (random order ids are
  excluded). A live-recorded run replays to the same realized P&L in the integration test.
* 12 new tests, 178 total. No change to risk, orders, auth, or defaults.
* Not verified: replay over a long real recording (none exists yet), performance on large histories
  (rows are loaded into memory), and anything about strategy quality.
* Next: strategy evaluation report (needs a minimum trade count and an out-of-sample split).

## 2026-11-11: quote and snapshot recorder (human-directed session, backlog item 1)

* Every `MarketSnapshot` the engine reads in a cycle is appended to a new `snapshots` table with
  recorded time, provider time, source, `fictional` and `timestamp_verified` flags and the full chain
  as JSON. Fictional rows are labelled and excluded from queries unless asked for. Config:
  `record_snapshots` (default on) and `snapshot_retention_days` (default 30, 1-3650); pruning runs at
  most hourly. A recording failure is reported in the cycle errors and never blocks exits or entries.
* New `snapshot_to_dict` / `snapshot_from_dict` (round-trip tested) so replay can read the rows back.
* 12 new tests plus an API test. Nothing in risk, orders, or auth changed.
* Measured: about 20 KB per snapshot on the demo chain. Real chains may differ; see BACKLOG ideas.
* Not verified: recording against the live Yahoo feed, or growth over weeks of real use.

## 2026-11-11: market hours always enforced on real data (human-directed session)

* Found: the dashboard's "Enforce market hours" box could be saved off while using Yahoo data. The
  engine would then trade on stale, unverified after-hours quotes. The owner's saved settings showed
  exactly that (entries on, hours off) with `OPTPLAT_DATA=yahoo`.
* Fix (tightening only): the switch is honoured only when the data provider is `fictional`. For real
  data hours are always enforced; `/api/engine/status` reports `market.hours_enforced` and the
  dashboard shows the box ticked and disabled.
* Test change, for the reviewer: `test_market_hours_enforcement_can_be_switched_off_for_demos` now
  sets `provider.fictional = True`, because that is the only case where the behaviour it describes is
  still allowed. Added two tests that it cannot be switched off for non-fictional data. No assertion
  was removed or loosened. 146 tests pass.
* Not verified: Yahoo against the live feed.

## 2026-11-11: one-command launcher (human-directed session)

* Added `run.sh`: finds Python 3.10+, creates `.venv`, installs once, starts the server, opens the
  dashboard already connected. `./run.sh yahoo` is the explicit opt-in for unverified Yahoo quotes
  (sets `OPTPLAT_ALLOW_UNVERIFIED_QUOTES=1` and the startup warning prints). The default `./run.sh`
  stays on the fictional demo market and keeps the strict quote-time check.
* Dashboard reads `#token=...` from the URL fragment once, keeps it in `sessionStorage`, and scrubs
  it with `history.replaceState`. Token checks in `api.py` are unchanged. Reviewer: this is the one
  change that touches how the token reaches the browser; the token is one-off and local-only.
* `--loop` / `OPTPLAT_AUTOSTART_LOOP=1` only starts the runner. `auto_entries` still comes from saved
  config and still defaults to off.
* Verified: 151 tests; a clean-copy `./run.sh demo --loop` (venv, install, start) and a headless
  Chromium load of the fragment URL (connected, URL scrubbed, loop running, entries off).
* Not verified: macOS (the owner's machine), `./run.sh yahoo` against the live feed, and
  `webbrowser.open` on a real desktop (no browser in the sandbox).

## 2026-11-11: token UX and Yahoo quickstart (human-directed session)

* `python -m optplat` now generates and prints a one-off token when `OPTPLAT_API_TOKEN` is unset,
  instead of exiting. The owner could not find the token generated by a shell one-liner. A supplied
  token must still be 16+ characters, and `create_app` still enforces that. Reviewer: please confirm
  you are comfortable with this startup behaviour change (it touches how auth is bootstrapped, not
  the checks themselves).
* Startup now prints the dashboard URL, broker/data mode, and loud warnings for demo data and for the
  unverified-quotes opt-in. README gained a "Run with free online data (Yahoo)" section.
* Not verified: the Yahoo provider against the live network from this environment (see the PR).

## 2026-11-11: initial MVP (human-directed session)

* Built the MVP on branch `mvp`: sell-to-close, exits, data providers, baseline strategy, engine,
  runner, dashboard. 140 tests pass.
* Found and fixed while testing: a routine reconcile refreshed `updated_at` on resting orders, which
  would have prevented stale-order cancellation.
* Added a same-underlying/direction concentration limit after a demo run piled five QQQ puts into one
  name.
* Not verified: any real broker, any real market data, performance on anything but a synthetic
  random-walk market (where the baseline loses money, as expected).

## 2026-11-14: GEX display upgrade (owner approved after research)

* `signals.gex` kept its original `total_usd_per_1pct` and `flip_strike`, and added: `gross_usd_per_1pct` (no sign assumption),
  both dealer-sign conventions (exact mirrors, so the sign is shown to be an assumption), `zero_gamma_spot` (chain revalued
  at 85-115% of spot, a model estimate), and `skip_reasons`. Quotes with IV above 300% or strikes beyond ~30% from spot are skipped and counted.
* Why: published evidence (Baltussen, Da, Lammers, Martens, JFE) concerns index/futures momentum into the close, not
  single names or multi-day direction. Public GEX infers dealer inventory from open interest plus an assumed sign.
  On the 2026-11-14 SPY/QQQ snapshots the net figure is near zero and flips sign with the convention.
* Observed on that data: the old `flip_strike` (cumulative strikes) gave 570 for SPY while `zero_gamma_spot` gave 756.59 with spot 757.12.
  The old flip is a weak summary; do not read anything into it.
* Verified: 555 tests pass (3 new). Ran against the Mac database snapshots (read-only copy). Not verified: any predictive value.
  Only ~3 trading days of snapshots exist. Nothing uses GEX in a decision; `VALIDATED_SIGNALS` is still empty.

## 2026-11-14: signal provenance doc (challenge 5, scheduled run on agent/integration)

* Added `docs/SIGNALS.md` (every signal, inferred label and post-mortem tag, with origin, status, caveat) and
  `tests/test_signal_provenance.py` (fails if a signal, tag or status drifts from the code; no edge claims).
  Taken from `origin/agent/2026-11-14-challenger-i` (docs and test files only), then updated the `gex_total` row for the
  GEX upgrade already on integration, plus one test for it. Docs and tests only; no source change.
* Deliberately NOT folded in: the rest of that branch (`marks.py`, `orders.py`, `trades.py` changes). It touches order
  code and conflicts with integration docs; the owner should decide whether to fold the many unmerged `agent/2026-11-1[34]-*`
  branches, which overlap each other (several redo the same provenance doc).
* Verified: full test suite, 565 passed. Not verified: that every row's origin text is accurate beyond reading the code.

## 2026-11-15: tracker 30 trading day marks (scheduled run on agent/integration)

* Backlog item 00 (part): `tracker.HORIZONS` gained 30 and `WATCH_DAYS` went from 12 to 50 calendar days (30 trading days plus the 2-day late-mark slack is about 46), otherwise a flag would drop off the watch list long before day 30. The Tracker page lists the 30 day mark beside 1, 3 and 7. Findings still read only the 3 day horizon. Display and research only: no orders, no risk or sizing change, nothing reads these marks for a decision.
* Also `store.record_unusual` now keeps 60 days of sightings instead of 30 (the tracker reads that table; at 30 days the 30 trading day mark could never fill). This only retains more rows; nothing is deleted that was kept before.
* Existing flags older than 12 days that were already dropped are not recovered; 30 day marks start filling for flags seen from now on (and any still within 50 days).
* Not done: the "chains read" count, and the owner decision on letting the `flow` agent support a trade.
* Verified: full test suite, 570 passed (retention test and horizon-due cases for 29, 30, 32 and 33 days added). Not verified: the dashboard in a browser, or any real 30 day marks (they need about six weeks of real scans).
* Merge status: PR #11 (`agent/integration` into `main`) was opened but NOT merged: GitHub reports it conflicts with `main` (main has commits integration lacks). The repo has no check runs on the branch; local tests (570 passed) were the gate. Left open for the owner or the next run to resolve. No documented path from `main` to the owner's Mac was found, so nothing could reach it.

## 2026-11-16: refresh the page to get the new build (owner request, interactive)

* Owner chose options-platform and a tested `stable` branch. Added `src/optplat/deploy.py` (build id; `request_update`, which launches `deploy/update.sh` only when `OPTPLAT_MANAGED=1`, at most every 5 minutes, with no caller input), `build_id` on `/api/health`, token-protected `POST /api/deployment/check-on-refresh`, dashboard check on first connected load that reloads when the build changes, `deploy/install_mac.sh`, `deploy/update.sh`, `deploy/server-wrapper.sh`, `.github/workflows/promote-stable.yml` and `docs/DEPLOYMENT.md`.
* Auth is unchanged except for one new endpoint that requires the existing token. No risk, sizing or order code touched.
* Verified: full test suite, 578 passed (8 new), shell syntax checks, workflow YAML parses. Not verified: anything on macOS (launchd, the installer, the updater), the workflow on GitHub, the dashboard in a browser.
* Blocker: `agent/integration` still conflicts with `main` (13 files, 36 hunks, tried locally and aborted). Until that is resolved and merged, nothing integrated can reach `stable`.

## 2026-11-10: quote and snapshot recorder (scheduled agent run)

* Backlog item 1. New `market_snapshots` / `market_quotes` tables plus `Store.record_snapshot`,
  `record_quotes`, `recorded_snapshots`, `recorder_counts`, `purge_market_data`. The engine records every
  snapshot it fetches and the held-position quotes it pulls. Recording is best effort: a storage error is
  reported in the cycle's `errors` and never blocks exits or entries.
* New engine config: `record_market_data` (default on) and `record_retention_days` (default 90; 0 keeps
  everything; validated 0-3650). Retention is applied at the end of each cycle. No safety control,
  risk limit or auth code was touched.
* Verified: 156 tests pass (11 new in `tests/test_recorder.py`: contents, time order, disable switch,
  fictional flag, failure isolation, transaction rollback, retention).
* Not verified: growth of the database over weeks against Yahoo (a 20-symbol watchlist at a 5 minute
  interval stores a full chain sample per cycle; the 90 day default is a guess the owner should tune),
  and no migration path for existing databases beyond `CREATE TABLE IF NOT EXISTS` (new tables only).


## 2026-11-15: closed-trade summary (scheduled challenger run)

* Compared with options-alerter (reviewed to `0107246`; see `docs/COMPARISON_ALERTER.md`). The alerter
  labels fill modelling and returns null stats for empty samples; the platform reported no results at all.
* Added `optplat/evaluation.py` and token-protected `GET /api/results`. Read-only, no change to risk,
  orders, auth or sizing. 6 new tests; 162 pass.
* Not verified: behaviour on real or Yahoo data; no commissions are modelled (logged as challenge 1).

## 2026-11-15: open-position marks (scheduled challenger run 2)

* Alerter unchanged since `0107246`; read `day_limits.py` (see comparison doc).
* `/api/results` now has `open_positions`: unrealized P&L marked to the bid, only from valid,
  venue-timestamped quotes under 120s old; any unmarkable position makes the total null and is listed
  with a reason. Broker errors fail closed. No risk, order, auth or sizing code touched. 4 new tests; 166 pass.
* Not verified: behaviour against a real broker's `get_positions`/`get_quote`; no commissions modelled.

## 2026-11-15: split-half check (scheduled challenger run 3)

* Alerter advanced to `123eed9` (local durable reports); read `local_reports.py`, `liquidity.py`.
* `/api/results` gains `split_half`: first vs second half of chronologically ordered closed trades;
  numbers withheld below the 30-trade gate; `consistent` false on opposite or zero signs. Display only; no
  risk, order, auth or sizing code touched. 3 new tests; 169 pass.
* Not verified: behaviour on real data; this is a stability check, not out-of-sample validation. PR/merge result: see below.

## 2026-11-15: dashboard Results panel (scheduled challenger run 4)

* Alerter advanced to `a7a2ca0` (dashboard redesign); read its UI diff. Weekend scan attempted: Yahoo is blocked by this session's egress proxy, so
  `docs/MONDAY_PLAN.md` records that no real data was reachable (no demo data used).
* Added a Results panel to the dashboard fed by `/api/results`. Frontend only; no risk, order, auth, sizing or
  broker code touched. 1 new test; 170 pass.
* Not verified: rendering in a real browser (only `node --check` and a static test); behaviour on real data.

## 2026-11-15: why-skipped panel (scheduled challenger run 5)

* Alerter unchanged at `a7a2ca0`; read `gex.py`. Added `explain_no_proposal` to `LiquidTrendStrategy`, a `reason`
  field on `NO_PROPOSAL` cycle entries and a dashboard Decisions panel (textContent only). No risk, order, auth,
  sizing or broker code touched; `propose` untouched. 4 new tests; 174 pass.
* Weekend scan: Yahoo unreachable from this session (curl returned no response); MONDAY_PLAN updated, no demo data used.
* Not verified: rendering in a real browser (only `node --check`); behaviour on real data. The Mac copy is a manual
  git clone, so this is not on the Mac until the owner updates it. PR/merge result: see PR.

## 2026-11-15: top candidates panel (scheduled challenger run 6)

* Alerter unchanged at `a7a2ca0`; read `market_breadth.py`. Added `candidates` to the cycle report and a dashboard
  Top candidates panel (textContent only). No risk, order, auth, sizing or broker code touched; `propose` untouched.
  1 new test; 175 pass.
* Weekend scan: Yahoo still refused by the egress proxy; MONDAY_PLAN updated, no demo data used.
* Not verified: rendering in a real browser (only `node --check`); behaviour on real data. The Mac copy is a manual
  git clone, so this is not on the Mac until the owner pulls. PR/merge result: see PR.

## 2026-11-15: net GEX panel (scheduled challenger run 7)

* Alerter unchanged at `a7a2ca0`; re-read `gex.py`. Added `optplat/gex.py`, `gex`/`gex_assumptions` in the cycle report
  and a dashboard panel (textContent only), labelled as an assumption on a sample chain. No risk, order, auth, sizing or
  broker code touched; `propose` untouched. 5 new tests; 180 pass.
* Weekend scan: Yahoo unreachable from this session; MONDAY_PLAN updated, no demo data used.
* Not verified: rendering in a real browser (only `node --check`); behaviour on real chains; correctness of the formula
  against the alerter's output on identical input. The Mac copy is a manual git clone, so this is not on the Mac until the
  owner pulls. PR/merge result: see PR.

## 2026-11-15: "At a glance" dashboard strip (scheduled challenger run 8)

* Alerter unchanged at `a7a2ca0`; read `sizing.py`. Added `buildGlance`/`renderGlance` and a dashboard section (textContent
  only); the refresh now also reads `/api/risk/policy`. No risk, order, auth, sizing or broker code touched. 1 new test
  (executes `buildGlance` under node); 181 pass.
* Weekend scan: Yahoo unreachable from this session; MONDAY_PLAN unchanged in substance, no demo data used.
* Not verified: rendering in a real browser (only `node --check` and the node-run test); behaviour on real data. The Mac copy
  is a manual git clone, so this is not on the Mac until the owner pulls. PR/merge result: see PR.

## 2026-11-15: volume/OI on candidates (scheduled challenger run 9)

* Alerter moved to `80672a6`; read `unusual_activity.py` (see COMPARISON_ALERTER). Added `volume`/`open_interest` to cycle-report
  candidates, two dashboard columns (textContent only, "not reported" for null) and a distinct skip reason for unreported
  volume/OI in `explain_no_proposal`. No risk, order, auth, sizing or broker code touched; `propose` untouched. 1 new test, 1
  updated for the new fields; 182 pass.
* Weekend scan: Yahoo unreachable (HTTP 000, proxy refused); MONDAY_PLAN updated, no demo data used.
* Not verified: rendering in a real browser (only `node --check`); behaviour on real chains. The Mac copy is a manual git clone,
  so this is not on the Mac until the owner pulls. PR/merge result: see PR.

## 2026-11-16: glance market/stall lines (scheduled challenger run 10)

* Alerter unchanged at `80672a6`; read `strategy_performance.py`. `buildGlance` now reports market open/closed, warns when the
  market-hours check is off, and warns when a running loop has not started a cycle in 3x its interval. textContent only. No
  risk, order, auth, sizing or broker code touched. Existing glance node test extended; 182 pass.
* No weekend scan (Monday); MONDAY_PLAN unchanged.
* Not verified: rendering in a real browser (only `node --check` and the node-run test); the stall rule against a real runner.
  The Mac copy is a manual git clone, so this is not on the Mac until the owner pulls. PR/merge result: see PR.


## 2026-11-16: fill-model label (scheduled challenger run 11)

* Alerter unchanged at `80672a6`; read `entry_quality.py`. Added `describe_fill_model`, `fill_model` in `/api/results` and a
  dashboard row (textContent only). No risk, order, auth, sizing or broker code touched. 184 pass.
* No weekend scan (Monday); MONDAY_PLAN unchanged.
* Not verified: rendering in a real browser (only `node --check` and string-pinning tests); behaviour with the IBKR adapter
  (reports "unknown" by design). The Mac copy is a manual git clone, so this is not on the Mac until the owner pulls.
  PR/merge result: see PR.

## 2026-11-16: server-side runner health (scheduled challenger run 12)

* Alerter unchanged at `80672a6`; read `day_limits.py`. `Runner.status()` now reports `last_success_at`, `last_failure_at`,
  `consecutive_failures`, `seconds_since_success`, `stalled`; the glance strip shows failure streaks and server stalls. No
  risk, order, auth, sizing or broker code touched. 2 new tests plus the glance node test extended; 186 pass.
* No weekend scan (Monday); MONDAY_PLAN unchanged.
* Not verified: rendering in a real browser (only `node --check` and the node-run test); behaviour of a real stuck cycle (a hung
  `run_cycle` is detected by age only after the next status call). The Mac copy is a manual git clone, so this is not on the
  Mac until the owner pulls. PR/merge result: see PR.

## 2026-11-16: closed-trade P&L path (scheduled challenger run 13)

* Alerter unchanged at `80672a6`; read `daily_review.py`. `/api/results` now has `cumulative_pnl_recent_usd`, `cumulative_pnl_points_total` and
  `longest_losing_streak`; the Results panel shows them as text. No risk, order, auth, sizing or broker code touched. 2 new tests; 188 pass.
* No weekend scan (Monday); MONDAY_PLAN unchanged.
* Not verified: rendering in a real browser (only `node --check`); behaviour on real trades. The Mac copy is a manual git clone, so this is not
  on the Mac until the owner pulls. PR/merge result: see PR.

## 2026-11-16: rolling outcome tally (scheduled challenger run 14)

* Alerter unchanged at `80672a6`; read `exit_decisions.py`. Engine now stores a bounded tally of entry result codes per cycle
  (`outcome_history` state, 50 cycles); `/api/engine/status` has `recent_outcomes`; Decisions panel shows one text line. No risk, order,
  auth, sizing or broker code touched. 2 new tests; 190 pass.
* No weekend scan (Monday); MONDAY_PLAN unchanged.
* Not verified: rendering in a real browser (only `node --check` and string-pinning tests). The Mac copy is a manual git clone, so this is
  not on the Mac until the owner pulls. PR/merge result: see PR.

## 2026-11-16: exit plan on open positions (scheduled challenger run 15)

* Alerter unchanged at `80672a6`; read `session_replay.py`. Added `exits.exit_plan`, `TradingEngine.exit_plans()` and `exit_plans` in
  `/api/engine/status`; Open positions panel shows take-profit bid, stop bid, expiry-exit window and whether automatic exits are ON.
  textContent only. No risk, order, auth, sizing or broker code touched. 3 new tests; 193 pass.
* No weekend scan (Monday); MONDAY_PLAN unchanged.
* Not verified: rendering in a real browser (only `node --check` and string-pinning tests); behaviour on real positions. The Mac copy is
  a manual git clone, so this is not on the Mac until the owner pulls. PR/merge result: see PR.

## 2026-11-16: promotion-readiness checklist (scheduled challenger run 16)

* Alerter unchanged at `80672a6`; read `strategy_postmortems.py`. Added `promotion_readiness` and `promotion` in `/api/results`; Results
  panel row "Ready to promote beyond paper?" (textContent only). No risk, order, auth, sizing or broker code touched. 2 new tests; 195 pass.
* No weekend scan (Monday); MONDAY_PLAN unchanged.
* Not verified: rendering in a real browser (only `node --check` and string-pinning tests). The Mac copy is a manual git clone, so this is
  not on the Mac until the owner pulls. PR/merge result: see PR.

## 2026-11-16: fee headroom (scheduled challenger run 17)

* Alerter unchanged at `80672a6`; read `risk.py`. Added `breakeven_fee_per_contract` and two fields in `/api/results`; Results panel row
  "Fee headroom" (textContent only). No risk, order, auth, sizing or broker code touched. 1 new test; 196 pass.
* No weekend scan (Monday); MONDAY_PLAN unchanged.
* Not verified: rendering in a real browser (only `node --check` and string-pinning tests). The Mac copy is a manual git clone, so this is
  not on the Mac until the owner pulls. PR/merge result: see PR.

## 2026-11-16: size-vs-liquidity note (scheduled challenger run 18)

* Alerter unchanged at `80672a6`; read `liquidity.py` (see comparison doc). Monday: no weekend scan.
* UX challenge: entry size was not shown against reported volume/OI. Added `optplat/liquidity.py` and a display-only
  `size_vs_liquidity` on each entry plus a "Size check" in the Decisions panel. Nothing blocks or resizes; no risk, order, auth,
  sizing or broker code touched.
* Verified: 197 tests pass (1 new); app.js parses. Not verified: dashboard rendering in a browser; behaviour on real data.
* The owner's Mac copy is a manual git clone; merged code is not there until the owner pulls.

## 2026-11-16: unusual options flow radar (owner request, run 18b)

* Added `optplat/flow.py`, `flow`/`flow_themes`/`flow_caveats` in the cycle report, a dashboard panel, 4 tests (201 pass), and docs
  `FLOW_CRITERIA.md` and `ALERTER_FLOW_HANDOFF.md`. Display only: no risk, order, auth, sizing or broker code touched.
* Not done: alerter changes (read-only here; accounts are on the Mac), flow as a trade trigger (owner decision), a Mac auto-start
  for the platform (needs the owner; the platform still needs a running process and token). Not verified: live Yahoo data, browser rendering.

## 2026-11-16: flow-following strategies (owner request, run 18c)

* Added `FlowFollowStrategy` with two modes and `OPTPLAT_STRATEGY` selection in `__main__.py` (default `liquid-trend`). 5 tests, 205 pass.
* Risk policy, sizing, auth, broker untouched; proposals still pass through the same risk gate and size cap. Paper only.
* Not verified: live Yahoo chains, how often flows pass the filters, any outcome. Not done: relaxing min DTE (owner), a dashboard strategy switch, alerter lanes (Mac-only; see ALERTER_FLOW_HANDOFF).

## 2026-11-16: worst-case line in the glance strip (scheduled challenger run 19)

* Alerter unchanged at `80672a6`; read `goal_sprint.py` (see comparison doc). Monday: no weekend scan.
* UX challenge: the owner could not see at a glance how much open premium can be lost outright. Added a display-only "Worst case today"
  line to `buildGlance` (textContent only). No risk, order, auth, sizing or broker code touched.
* Verified: 205 tests pass (existing node-harness test extended); app.js parses. Not verified: rendering in a browser.
* The owner's Mac copy is a manual git clone; merged code is not there until the owner pulls. PR/merge result: see PR.

## 2026-11-16: multiple-testing note (scheduled challenger run 20)

* Alerter moved to `30c64d7` (whale thesis dossiers, GEX confluence policy); read, see comparison doc. Monday: no weekend scan.
* UX/challenge 3: three strategies are selectable but Results showed one total. Added display-only `multiple_testing` to `/api/results` and a Results row (textContent only). No risk, order, auth, sizing or broker code touched.
* Verified: 206 tests pass. Not verified: rendering in a browser; per-strategy results (orders do not record the strategy).
* The owner's Mac copy is a manual git clone; merged code is not there until the owner pulls. PR/merge result: see PR.

## 2026-11-16 (run 21, challenger)

* Changed: dashboard glance now shows "Strategy in use" from `/api/engine/status.strategy` (name, version, no-edge note, results-not-split warning); unknown shows a warning. Frontend only.
* Verified: `python -m pytest -q` 206 pass (glance node test extended, runs under node 22). Alerter unchanged at `30c64d7`.
* Not verified: not viewed in a real browser; no real market data (cloud run, Monday, no weekend scan). Not on the owner's Mac until they pull their clone.

## 2026-11-16 (run 22, challenger)

* Alerter unchanged at `30c64d7`; read `market_clock.py`. Monday: no weekend scan.
* Changed: `upcoming_closures()` in `market_clock.py`, `market.upcoming` in engine status, one glance line. Display only; holiday table, risk, auth, broker untouched.
* Verified: 208 pass (2 new tests, node glance test extended). Not verified: browser rendering; real data (cloud run). Not on the owner's Mac until they pull their clone.

* 2026-11-16 (run 23): Added display-only last-trade age to Top candidates (`ChainRow.last_trade_at`, `last_trade_age_hours`, dashboard column). Verified: 210 pytest pass, `node --check app.js`. Not verified: rendering in a real browser, behaviour on real Yahoo data (unreachable from cloud). No risk/order/auth/broker change. Mac copy is a manual clone; arrival not confirmed.

## 2026-11-16 (run 24): glance sorted by urgency

* Alerter unchanged at `30c64d7`; read `technical_confluence.py` (see COMPARISON_ALERTER). Monday, no weekend scan.
* Changed: `renderGlance` orders lines bad, warn, ok (stable) and shows counts. Frontend only; DOM still textContent only.
* Verified: `python -m pytest -q` 210 pass, including the node harness (ordering and stability asserted). Not verified: appearance in a real browser; Mac copy is a manual git clone, so merged code is not on the Mac until the owner pulls.

## 2026-11-16 (run 25): no-daily-loss-halt glance warning

* Alerter unchanged at `30c64d7`; read `feedback.py`. Monday, no weekend scan.
* Changed: one glance note when auto entries are ON saying there is no daily loss halt. Frontend only; DOM textContent only.
* Verified: 210 pytest pass (node glance test extended). Not verified: real browser. Mac copy is a manual git clone; merged code is not on the Mac until the owner pulls.

## 2026-11-16: merged `main` into `agent/integration` (interactive, owner said always attempt it myself)

* `main` had 55 commits from per-topic agent branches; many re-implemented features integration already had. Resolution rules: integration wins where both sides built the same thing; main-only features are kept; nothing was deleted from either side.
* Name clashes resolved: main's `evaluation.py` (closed-trade summary, `/api/results`) is now `closed_trades.py` (integration's `evaluation.py` is the replay-based strategy evaluation); main's quote recorder methods are `record_market_snapshot`, `record_market_quotes`, `recorded_market_snapshots`, `market_recorder_counts`, with their tests in `tests/test_market_recorder.py`; main's `docs/CHALLENGES.md` and `docs/COMPARISON_ALERTER.md` are kept as `docs/CHALLENGES_MAIN.md` and `docs/COMPARISON_ALERTER_MAIN.md`.
* Two recorders now run side by side (integration's `snapshots` table and main's `market_snapshots`/`market_quotes`), so recorded data is stored twice. Owner or a later run should pick one; both are bounded by their own retention settings.
* Dashboard: integration's v2 layout is the base. Main's glance strip, results panel, why-skipped, top candidates, flow radar and GEX panels sit on the Desk page; main's exit levels are added to each position card; main's `renderDecisions` became `renderCycleDecisions`. Runner health merged (stall check kept from integration; failure counters and `status(now)` from main). `__main__` keeps both the strategy choice (`OPTPLAT_STRATEGY`) and the event calendar.
* Test change to say plainly: the node harness in `test_glance_summary_is_text_only_and_flags_unsafe_states` gained browser stubs (matchMedia, location, history) because the v2 script touches them at load; no assertion was changed.
* Verified: full suite, 644 passed; headless Chromium against the demo server loaded every page with no script errors and showed the build id, glance and results. Not verified: real data, the Mac, the GitHub workflow.
