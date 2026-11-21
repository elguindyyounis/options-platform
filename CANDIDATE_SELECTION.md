# Movement versus option cost — v1

New research selections require at least 21 valid daily closes, a valid two-sided quote and IV. No ticker blacklist is used. Existing position exits are not screened by this entry policy.

The favorable scenario uses the RMS of the last 60 daily log returns scaled by the square root of a holding period of at most 10 trading sessions, shortened to remain before expiry. It is a magnitude scenario in the option direction, not a directional prediction, expected return or probability. Daily bars cannot establish an intraday opportunity.

Option value changes use a zero-rate, zero-dividend European approximation anchored to the quoted bid. The scenario deducts elapsed calendar time, the observed spread, 0.5% entry/exit slippage and $0.65 per contract each way. A candidate must show at least 10% favorable scenario net return and a nonnegative favorable return when IV falls by 20%. These are provisional research thresholds, not empirically validated optimal cutoffs. Flat and adverse scenarios are disclosed alongside favorable results.

Missing inputs and implausible/discontinuous history fail closed. Passing never removes liquidity, quote freshness, portfolio, skeptic or broker risk requirements. American exercise, dividends, volatility smiles, gaps, changing spreads and execution availability are not fully modeled. Delayed sources remain delayed.

The output records the version, sample count, horizon, premium, target, scenarios and reasons. Verify selection quality prospectively using saved snapshots and net paper outcomes before claiming improved profitability. Historical results must not be relabeled under the new policy.
