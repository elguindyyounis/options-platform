"""Weekly research report: what happened, what failed, and which questions are worth a pre-registered test.

Rule-based and deterministic. It reads the database through a read-only handle, so it cannot place orders,
register hypotheses, change settings or edit its own grading. Proposals are questions for the owner, each
with the evidence behind it and the sample-size caveat; acting on one is the owner's decision.

    python -m optplat.weekly --db optplat.db [--days 7] [--fictional] [--out report.md]
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta
from typing import Any, Optional

from .evaluation import MIN_TRADES, equity_summary
from .journal import MIN_SAMPLE, journal_summary
from .models import utcnow
from .store import Store

MIN_REJECTIONS_FOR_PATTERN = 20  # fewer rejections than this is noise, not a pattern
DOMINANT_SHARE = 0.5
RANKING_GAP_PCT = 2.0  # passed-over candidates must beat chosen ones by this many points before it is worth asking


def _when(ts: str) -> datetime:
    return datetime.fromisoformat(ts)


def build_report(store: Store, now: datetime, days: int = 7, include_fictional: bool = False) -> dict[str, Any]:
    since = now - timedelta(days=days)
    decisions = [d for d in store.list_decisions(include_fictional=include_fictional, newest_first=False, limit=100_000)
                 if _when(d["ts"]) >= since]
    by_disposition: dict[str, int] = {}
    reject_reasons: dict[str, int] = {}
    for d in decisions:
        key = f"{d['kind']}:{d['disposition']}"
        by_disposition[key] = by_disposition.get(key, 0) + 1
        if d["disposition"] == "RISK_REJECTED":
            for reason in d["payload"].get("risk_failures") or ["(no reason recorded)"]:
                reject_reasons[reason] = reject_reasons.get(reason, 0) + 1
    points = [p for p in store.list_equity(limit=5000, fictional=include_fictional) if _when(p["ts"]) >= since]
    journal = journal_summary(store, now, include_fictional=include_fictional)
    issues = store.data_issue_summary(since)
    hypotheses = []
    for h in store.list_hypotheses():
        results = store.hypothesis_results(h["id"])
        hypotheses.append({"id": h["id"], "statement": h["payload"]["statement"],
                           "status": results[-1]["status"] if results else "NOT_EVALUATED"})
    report: dict[str, Any] = {
        "generated_at": now.isoformat(), "since": since.isoformat(), "days": days, "fictional": include_fictional,
        "decisions": by_disposition, "rejection_reasons": dict(sorted(reject_reasons.items(), key=lambda kv: -kv[1])),
        "equity": equity_summary(points), "data_issues": issues, "recorder": store.snapshot_stats(),
        "forward_returns": journal["forward_return_by_disposition"], "hypotheses": hypotheses,
    }
    report["proposals"] = propose(report)
    return report


def _group(report: dict[str, Any], name: str, horizon: str = "24h") -> dict[str, Any]:
    return report["forward_returns"].get(name, {}).get(horizon, {"matured": 0, "mean_return_pct": None})


def propose(report: dict[str, Any]) -> list[dict[str, str]]:
    """Questions worth a pre-registered test. Never an instruction to change a limit or a threshold."""
    out: list[dict[str, str]] = []
    drops = sum(v["items"] or 0 for v in report["data_issues"].values())
    if drops:
        out.append({"title": "Fix data reliability before testing anything",
                    "evidence": f"{drops} data-quality items in the period: " + ", ".join(sorted(report["data_issues"])),
                    "next": "Check the provider and the quote timestamps. Results measured on this data are not trustworthy."})
    total = sum(report["rejection_reasons"].values())
    if total >= MIN_REJECTIONS_FOR_PATTERN:
        reason, n = next(iter(report["rejection_reasons"].items()))
        if n / total > DOMINANT_SHARE:
            out.append({"title": "One risk rule rejects most candidates",
                        "evidence": f"'{reason}' caused {n} of {total} rejections in the period.",
                        "next": "Owner decision: whether the rule is right or the strategy proposes the wrong contracts. "
                                "An agent must not loosen the rule. A challenger that filters candidates earlier is a "
                                "legitimate experiment to pre-register."})
    chosen, passed = _group(report, "FILLED"), _group(report, "NOT_CHOSEN")
    if min(chosen["matured"], passed["matured"]) >= MIN_SAMPLE and None not in (chosen["mean_return_pct"], passed["mean_return_pct"]) \
            and passed["mean_return_pct"] - chosen["mean_return_pct"] >= RANKING_GAP_PCT:
        out.append({"title": "Is the ranking picking worse contracts than the ones it passes over?",
                    "evidence": f"24h forward bid return: passed over {passed['mean_return_pct']}% vs chosen "
                                f"{chosen['mean_return_pct']}% (n={passed['matured']} / {chosen['matured']}; candidates overlap in time).",
                    "next": "Pre-register a challenger with a different score weighting, then evaluate it confirmatory."})
    elif min(chosen["matured"], passed["matured"]) < MIN_SAMPLE:
        out.append({"title": "No ranking question yet",
                    "evidence": f"Only {chosen['matured']} chosen and {passed['matured']} passed-over candidates have a 24h outcome; "
                                f"at least {MIN_SAMPLE} of each are needed.",
                    "next": "Keep the loop running on real recorded data."})
    return out


def format_report(r: dict[str, Any]) -> str:
    eq = r["equity"]
    lines = [f"# Weekly research report ({r['days']} days to {r['generated_at'][:10]})", ""]
    lines.append("Rule-based and read-only. It registers nothing, changes nothing and does not claim an edge." +
                 (" **Data is FICTIONAL: results prove nothing.**" if r["fictional"] else ""))
    lines += ["", "## Can the numbers be trusted?"]
    rec = r["recorder"]
    lines.append(f"* Snapshots recorded in total: {rec['real']} real, {rec['fictional']} fictional.")
    if r["data_issues"]:
        for kind, v in r["data_issues"].items():
            lines.append(f"* {kind.lower().replace('_', ' ')}: {v['items']} items ({v['severity']})")
    else:
        lines.append("* No data-quality issues logged in the period.")
    lines += ["", "## Paper account"]
    if eq["points"] < 2:
        lines.append("* Not enough equity points in the period to say anything.")
    else:
        lines.append(f"* Equity {eq['start']:,.2f} to {eq['last']:,.2f} ({eq['change_pct']:+.2f}%), "
                     f"worst drawdown {eq['max_drawdown_pct']}%, over {eq['points']} points.")
    lines.append(f"* Anything under {MIN_TRADES} closed trades is not evidence of an edge.")
    lines += ["", "## Decisions in the period"]
    lines += [f"* {k}: {v}" for k, v in sorted(r["decisions"].items())] or ["* None recorded."]
    if r["rejection_reasons"]:
        lines += ["", "Top risk rejections:"] + [f"* {k}: {v}" for k, v in list(r["rejection_reasons"].items())[:5]]
    lines += ["", "## What happened to candidates after the decision (24h bid return)"]
    for name, grp in sorted(r["forward_returns"].items()):
        c = grp.get("24h")
        if c:
            lines.append(f"* {name}: {c['matured']} matured, {c['pending']} pending, {c['unobservable']} unobservable, "
                         f"mean {'n/a' if c['mean_return_pct'] is None else str(c['mean_return_pct']) + '%'}" + (" (descriptive only)" if c["descriptive_only"] else ""))
    lines += ["", "## Experiments"]
    lines += [f"* {h['id']} {h['status']}: {h['statement']}" for h in r["hypotheses"]] or ["* None registered."]
    lines += ["", "## Questions worth testing (owner decides; nothing here is registered)"]
    for p in r["proposals"]:
        lines += [f"* **{p['title']}.** {p['evidence']} Next: {p['next']}"]
    return "\n".join(lines) + "\n"


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Weekly research report from the recorded journal and results")
    ap.add_argument("--db", default="optplat.db")
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--fictional", action="store_true", help="report on demo data instead of real recorded data")
    ap.add_argument("--out", help="write the report to this file instead of printing it")
    args = ap.parse_args(argv)
    if not 1 <= args.days <= 365:
        print("Error: --days must be 1-365", file=sys.stderr)
        return 1
    try:
        store = Store(args.db, read_only=True)
        text = format_report(build_report(store, utcnow(), args.days, args.fictional))
    except Exception as exc:  # noqa: BLE001
        print(f"Error: could not read {args.db}: {type(exc).__name__}", file=sys.stderr)
        return 1
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(text)
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
