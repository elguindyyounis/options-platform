# Agent log

Append-only. One entry per agent run: date, what changed, what was verified, what was not.

## 2026-11-12: daily challenger, honest lane scoreboard

* Alerter unchanged since `9210fd8`. Read `agents.py`, `core.py` and the skeptic skill; notes added to `docs/COMPARISON_ALERTER.md`.
  The alerter can only be made stricter by its model and trips a skeptic hold on a cohort losing badly; the platform has no such tripwire.
* Challenged: five lanes judged on small samples and the bid exit make it likely that one lane looks good by luck. Added
  `src/optplat/scoreboard.py` (display-only): per lane, the average at the bid and at the harder exit, a normal-approximation
  interval widened for the number of lanes (Bonferroni), the best trade's share of gains, and a verdict that is TOO_FEW below 30
  closed trades. Exposed as `scoreboard` in the option-lanes report and as a dashboard panel (textContent only).
* Nothing a lane trades, no limit, size, default or auth was changed. 505 tests pass (8 new; one existing assertion made stricter).
* Not verified: the panel in a browser, any live Yahoo data or the owner's database, the alerter's own tests. The interval ignores
  overlap between trades and fat tails, so it is still optimistic.




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

## 2026-11-12: daily challenger, signal provenance

* Alerter unchanged since `9210fd8`. Read its `storage.py` (notes in COMPARISON_ALERTER.md).
* Based the branch on `agent/2026-11-12-daily-challenge` because `main` does not yet contain the challenge docs or lanes.
* Added `provenance.py` and `GET /api/research/provenance`: 14 signals/labels with origin, definition, caveat, and
  validation status. Nothing is VALIDATED; tests tie it to `signals.SIGNAL_NAMES` and `VALIDATED_SIGNALS`.
* No risk limit, lane size, default, auth check or trade behaviour changed. 510 tests pass.
* Not verified: alerter tests, completeness of the caveats, the endpoint in the live dashboard (none shown yet).
