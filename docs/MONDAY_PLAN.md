# Monday plan (research, not advice)

As of 2026-11-15 23:20 UTC (Sunday; rechecked, still unreachable: HTTP 000). Data source: none.

The weekend scan could not run. The only free provider the platform supports (Yahoo options chains) was
refused by this session's egress proxy (`query1.finance.yahoo.com` connection rejected), and no other free
source is wired in. The platform's demo provider is fictional, so no candidates are listed: showing demo
output here would pass fiction off as a market read.

* Top candidates: none (no real data).
* Known events next week: none verified; the platform has no trustworthy event calendar (backlog: blocked on a human).
* To get a real scan, run the platform on the Mac with `--data yahoo` (see README) and check `/api/engine/status`.
