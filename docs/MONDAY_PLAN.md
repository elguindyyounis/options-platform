# Monday plan (research, not advice)

As of 2026-11-28 02:40 UTC (Saturday). Run by the daily challenger from a cloud session, not from the owner's Mac. Replaces the 2026-11-22 version.

**Option scan: not run.** The platform's only option-chain provider (Yahoo) was refused by this session's egress proxy again (HTTP 403 at the
proxy, tested this run). No other free option-chain source is wired in, so no strategy output exists and **no candidates are listed, in or out**.
Demo data is fictional and is deliberately not used here.

## What real data was reachable

* **Underlying prices** (TradingView screener via the session's MCP; "streaming" mode, last session close and % change as returned, exact close
  time not stated, one source, not cross-checked): SPY 728.32 (+1.62%), QQQ 650.99 (+2.69%), IWM 273.79 (+1.83%), DIA 507.60 (+1.26%),
  GLD 334.40 (+2.12%), TLT 81.27 (-1.18%), AAPL 358.54 (+0.83%), MSFT 492.85 (+0.60%), NVDA 150.49 (+0.80%), TSLA 400.00 (+5.22%).
* **Same source, RSI(14) / 50-day / 200-day:** SPY 45.0 / 757.20 / 733.34 (below both); QQQ 44.0 / 705.73 / 683.69 (below both); IWM 50.1 /
  276.93 / 279.63 (below both, close); DIA 47.9 / 515.04 / 507.63 (at the 200-day); NVDA 38.1 / 202.28 / 202.68; MSFT 40.4 / 519.45 / 445.33;
  AAPL 60.2; TSLA 56.4; GLD 37.5; TLT 53.5.
* **What changed since the 2026-11-22 plan** (one source, so treat as a description): SPY was 689.81 with RSI 24.9; it is now 728.32 with RSI 45.0,
  a rebound of about 5.6% in prices. The market-regime guard (`regime.py`) is built for exactly this "oversold bounce" shape, so new puts may
  be held back on Monday's first cycles while calls are not. That is an observation about the guard, not a signal. The Trades page now counts
  entries held back by reason (UX-12), so a quiet put lane can be told apart from an idle one.
* The size of the moves (TSLA +5.2% in a session, QQQ +2.7%) is unusual; **verify on a second source before reading anything into it.**

## Known events, week of 2026-11-30 (source: TradingView economic calendar, US, medium and high importance; times UTC)

* Mon 11-30: Chicago PMI 14:45 (forecast 55, prior 55.3); Dallas Fed manufacturing 15:30; 3M/6M bill auctions 16:30.
* Tue 12-01: **ISM Manufacturing PMI** 15:00 (forecast 55, prior 55.5); **JOLTS job openings** 15:00 (forecast 7.5M, prior 7.52M); auto sales.
* Wed 12-02: ADP employment 13:15 (forecast 80K, prior 86K); EIA crude stocks 15:30.
* Thu 12-03: jobless claims 13:30 (forecast 195K); **ISM Services PMI** 15:00 (forecast 54.6, prior 54.5); factory orders; 4-week bill auction.
* Fri 12-04: **Non-Farm Payrolls** 13:30 (forecast 90K, prior 165K); unemployment rate (forecast 4.1%); average hourly earnings (forecast +0.3% MoM);
  Michigan sentiment preliminary 15:00 (forecast 52.5).
* The week is built around Friday's jobs report; the forecast for payrolls is well below the prior print, so Friday's reaction may be large either way.
* **Company earnings next week: unknown.** No trustworthy earnings source was reachable.
* Market holidays: none expected this week; the platform's holiday table was not touched (owner-only).

To get a real scan: run the platform on the Mac with `--data yahoo` and read `/api/engine/status`.
