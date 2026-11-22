# Monday plan (research, not advice)

As of 2026-11-22 02:20 UTC (Sunday); refreshed from the 2026-11-21 version. Run by the daily challenger from a cloud session, not from the owner's Mac.

**Option scan: not run.** The platform's only option-chain provider (Yahoo) was refused again by this session's egress
proxy (HTTP 000, re-tested this run). No other free option-chain source is wired in, so no strategy output exists and **no candidates are
listed**. Demo data is fictional and is deliberately not used here.

## What real data was reachable

* **Underlying prices** (TradingView screener via the session's MCP; last-session close and % change as returned, delay and
  exact close time not stated by the source, not cross-checked):
  SPY 689.81 (-3.64%), QQQ 608.45 (-5.67%), IWM 256.61 (-2.88%), DIA 481.08 (-1.98%), GLD 322.87 (-3.67%),
  AAPL 342.56 (-1.90%), MSFT 484.52 (-2.77%), TSLA 345.82 (-7.64%), NVDA 125.53 (-14.01%). TLT was not found.
  These are unusually large moves. **Verify on a second source before reading anything into them.** If true, implied
  volatility is probably high and the platform's spread and OI filters will behave differently than on a calm week.
* **Why that matters for the lanes (an observation, not a signal):** a broad drop of this size makes put-side lanes and
  every stop/target (percent of premium) hit sooner, and wide spreads make bid exits look worse than the ask-in entry.

* **Same source, second look (TradingView, same session close, still one source):** RSI(14) SPY 24.9, QQQ 26.6, IWM 30.2, DIA 27.0,
  GLD 23.7, NVDA 15.0, MSFT 34.8, TSLA 37.8, AAPL 46.4. SPY 689.81 is below its 50-day (760.18) and 200-day (732.76) averages; QQQ, IWM,
  DIA and MSFT too. Quotes are identical to the 11-21 pull, so nothing new has printed since Friday. The oversold readings are
  consistent with the large drops, which makes a data error less likely but is **not** a second source. Oversold can stay oversold;
  this is a description, not a signal.

## Known events, week of 2026-11-23 (source: TradingView economic calendar, US, medium and high importance; times UTC)

* Mon 11-23: Chicago Fed National Activity Index 13:30; S&P Global flash PMIs 14:45; 3M/6M bill auctions; 2Y note auction 18:00.
* Tue 11-24: Case-Shiller 20-city (Sep) 14:00; Conference Board consumer confidence 15:00 (forecast 92.5, prior 91.7); 5Y note auction 18:00.
* Wed 11-25 (13:30 and 15:00): **GDP 2nd estimate Q3** (forecast 3.4%, prior 1.5%), **Core PCE MoM** (forecast 0.3%), **Personal Income and
  Personal Spending MoM**, **Durable Goods**, jobless claims (forecast 200K), new home sales, 7Y note auction, EIA crude stocks.
  Releases are bunched on Wednesday, so the lanes should expect a volatile Wednesday morning.
* Thu 11-26: the calendar lists no US releases, consistent with the Thanksgiving market holiday. **The platform's holiday table was
  not touched** (owner-only, official exchange source needed); confirm the NYSE schedule, including an early close on Fri 11-27, yourself.
* Fri 11-27: only low-importance releases (goods trade balance, inventories).
* **Company earnings next week: unknown.** No trustworthy earnings source was reachable (Yahoo calendar blocked).

To get a real scan: run the platform on the Mac with `--data yahoo` and read `/api/engine/status`.
