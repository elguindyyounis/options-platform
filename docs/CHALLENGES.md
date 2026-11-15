# Challenges to the platform

Last alerter commit reviewed: d9ef3829771b770537007d8a95ec156cccb0b7ae

Each row is a place where a result could look better than it is, or where the alerter is stricter.

## Open challenges

| # | Challenge | Needs owner? | Status |
|---|---|---|---|
| C3 | (Partly addressed by C7: closed rows now show fill vs trigger bid.) Fixed take-profit/stop-loss evaluated only on cycle ticks; a gap through the stop fills at the worse bid in reality, the sim exits at the observed bid but nothing reports slippage vs the trigger. Idea: record trigger price vs fill. | No | Open |
| C4 | Baseline strategy is one lane on one trend rule; many tweaks tried on few trades would overfit. Needs the evaluation report (BACKLOG 3) with an out-of-sample split before any tuning. | No | Open, blocked on BACKLOG 1-2 |
| C9 | Alerter now has a per-day loss limit, entries-per-day cap and an entry window (`day_limits.py`, all off until set). The platform has none (BACKLOG item 3). The default values are a risk-policy decision. | Yes | Noted only |
| C10 | Alerter now ships an NYSE 2026-2028 holiday and early-close table. The platform's table stops earlier and fails closed for unknown years, which is safe but stops paper runs in 2027. Adding a year needs an official NYSE source cited in the PR. | Yes | Noted only |
| C6 | Alerter lane sizes are very large for experiments. Owner has chosen them; not changed here. | Yes | Noted only |

## Resolved

| C8 | Alerter keeps Yahoo `lastTradeDate` per contract; the platform ignored it, so a quote that had not traded for days looked as fresh as a busy one. | 2026-11-15 (run 5): `ChainRow.last_trade_at` (optional, parsed from `lastTradeDate`, naive or bad values become unknown); engine entries report `last_trade` (`RECENT`/`OLD` over 72 h/`UNKNOWN`). Display only: it does not filter entries, and it is kept out of the order intent because it changes every cycle and would trigger idempotency conflicts. 4 tests. |

| # | Challenge | Resolution |
|---|---|---|
| C1 | Headline equity valued unquotable positions at cost (hid losses); win rate shown with no sample warning. | 2026-11-15: `/api/report` gains `sample`, `marks_complete`, `open_unmarked`, `conservative_equity`; dashboard shows them. Display only; risk sizing still uses broker equity (a risk-policy question, left for the owner). |

| C2 | No exit-friction stress: exits assume the bid is hittable at size. | 2026-11-15 (run 2): per-position `exit_stress` scenarios and report-level `stressed_equity` (spread-only; no volume/OI on `Quote`, so thin-market risk is understated). Display only. |

| C7 | Platform closed rows carried no exit reason or exit quote time (alerter keeps `exit_reason`, `exit_quote_at`). | 2026-11-15 (run 3): engine writes an `exit_trigger` audit event per exit order (not part of the intent, so idempotency is untouched); `/api/report` closed rows show trigger, quote time, bid at decision and fill minus bid. Unrecorded closes read `UNKNOWN`. API only; dashboard not changed. Quote time is provider `as_of`; `quote_verified` says whether it is a real exchange time. |

| C5 | Does the platform ever mark Yahoo quote times verified (alerter labels them `exchange_quote_time_verified: False`)? | 2026-11-15 (run 4): verified by reading `YahooDataProvider`: snapshot and `quotes_for` always pass `False`, `as_of` is the download time. Now pinned by 2 offline tests (fake `yfinance`), including that default `RiskPolicy` rejects the quote. No behaviour change. |

## Run log (newest first)

| Date | Alerter commit | Challenged | Changed |
|---|---|---|---|
| 2026-11-15 (run 5) | d9ef382 (3 new commits) | C8 last-trade time as evidence; read alerter `day_limits.py`, `underlying_exits.py`, new `market_clock` table, `session_replay` head | `last_trade_at` on chain rows plus `last_trade` evidence in engine entry reports; 4 tests (`tests/test_last_trade_evidence.py`). Logged C9, C10 (owner) |
| 2026-11-15 (run 4) | 48ccf71 (no change) | C5 Yahoo quote time; read alerter `agents.py`, `data_sources.option_rows` | Tests only (`tests/test_yahoo_unverified.py`, 2): Yahoo snapshot and quotes are never verified, default policy rejects them. Found C8 |
| 2026-11-15 (run 3) | 48ccf71 (no change) | C7 exit trigger and quote time not auditable; read alerter `lane_paper_engine.monitor_lane_options` | `exit_trigger` audit record + `exit_trigger`, `exit_quote_at`, `trigger_bid`, `quote_verified`, `fill_vs_trigger_bid` on closed rows in `/api/report`; 4 tests |
| 2026-11-15 (run 2) | 48ccf71 (no change) | C2 exit-friction stress; read alerter `storage.py` head | `exit_stress()` + `stressed_equity` in `/api/report`, dashboard line, 2 tests |
| 2026-11-15 | 48ccf71 | C1 optimistic marks, small-sample labelling | Report fields + dashboard text + 4 tests; created these docs |
