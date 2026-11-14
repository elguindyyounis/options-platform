# Signal and label provenance

Every signal or label the platform computes, where it comes from, and what evidence exists for it. Written 2026-11-14
after reading `options-alerter/research_foundations.py`, which keeps the same kind of record. Nothing here is a claim of
edge. **No signal below has any validation**; `signals.VALIDATED_SIGNALS` is empty, and `tests/test_signal_provenance.py`
fails if this table and that set disagree, or if a signal or label is added without a row here.

Data behind all of it: free, delayed, unofficial chains (Yahoo) or fictional demo data. Open interest is the prior day's
figure, volume is a running day total, and quotes are not exchange-timestamp verified unless a feed says so.

## Computed signals (`signals.py`)

| Signal | Definition | Origin | Status | Main caveat |
| --- | --- | --- | --- | --- |
| `call_put_volume_ratio` | Sum of call volume over sum of put volume in one snapshot | Developer heuristic | UNVALIDATED | Hedging and closing trades look the same as bullish buying |
| `call_put_oi_ratio` | Same, using open interest | Developer heuristic | UNVALIDATED | Prior-day stock of positions, not new flow |
| `unusual_count` | Contracts over the volume, open-interest and volume/OI thresholds | Developer thresholds, alerter uses similar ones | UNVALIDATED | Thresholds were chosen, not fitted; the chain is a sample |
| `gex_total` | Modeled gamma exposure (Black-Scholes gamma, zero rate) under one dealer-sign convention | Standard model plus a contested assumption | UNVALIDATED | Needs who-holds-what; the sampled chain is partial |

## Inferred labels (scanner and journal)

| Label | Values | How it is inferred | Status | Main caveat |
| --- | --- | --- | --- | --- |
| `likely_side` | `BUY`, `SELL`, `UNCLEAR` | Last print against the bid and ask (`scanner.trade_side`) | UNVALIDATED | One price, not a tape; the last print may be a tiny share of volume |
| `position_read` | `BUY_TO_OPEN`, `SELL_TO_OPEN`, `BUY_TO_CLOSE`, `SELL_TO_CLOSE` or `UNCLEAR` (combines `likely_side` with the open-interest change) | Change in next-day open interest against the sighting day's volume (`compare_with_prior`) | UNVALIDATED | Spreads, rolls and late OI updates blur it |
| `flow_lean` | `BULLISH_LEAN`, `BEARISH_LEAN`, `BALANCED`, `UNCLEAR` | Unusual contracts printed at ask or bid, weighted by quoted turnover | UNVALIDATED | Built on `likely_side`, so it inherits that weakness |
| liquidity tier | `A`, `B`, `C` | Spread, volume and open-interest cut-offs (`liquidity_tier`) | UNVALIDATED | Heuristic; no book depth |

## Post-mortem cause tags (`postmortem.py`)

These describe why a closed paper trade ended as it did. They are rule-based descriptions of one trade, not tested causes.
A tag becomes a "pattern" only after the digest's minimum trade count, and even then it is a lead.

`TARGET_HIT`, `STOPPED_QUICKLY`, `STOPPED`, `WRONG_DIRECTION`, `RIGHT_DIRECTION_LOST_MONEY`, `TIME_DECAY`, `SPREAD_ATE_GAIN`,
`WIDE_SPREAD_ENTRY`, `STACKED`, `OVERSIZED_FOR_LIQUIDITY`, `THIN_MARKET`, `EARNINGS_GAMBLE`, `VWAP_LOST`, `FLAT_BY_CLOSE`,
`TREND_BREAK`, `TIME_STOP`, `EXPIRY_NEAR`, `UNMARKED`, `EXIT_STRESS_FLIPS_RESULT`, `BIG_WIN`

## What would change a status

A signal moves to validated only when the owner adds it to `VALIDATED_SIGNALS` after `study_signal` shows it on enough
independent observations and a pre-registered `research` experiment supports it. With many signals and many lanes, some
will look good by chance; the alerter cites Novy-Marx (NBER 2015) and Bailey et al. (2017) on exactly this, and the same
warning applies here.
