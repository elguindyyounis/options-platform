"""Standing objections: what this platform would challenge about its own results right now.

The point of a paper account is to be allowed to be wrong cheaply, so the dashboard should argue against the numbers
instead of flattering them. Everything here is computed from records the platform already keeps (closed trades from every
account and lane, the tracker, the clock check, the 10x challenge). It adds no trading rule and changes no limit. Each
objection says what the data shows, why it matters, and what would change its mind, so that it can be tested and retired
rather than repeated. With nothing to object to, it says so plainly; the absence of an objection is not proof of an edge.
"""
from __future__ import annotations

from typing import Any, Optional

MIN_N = 20                    # closed trades a lane needs before its average means anything
CONTROL_LANE = "control-random-swing"
RULE_LANE = "swing-options-base"
BEAT_MARGIN_PTS = 5.0         # average return points the real rule must lead the random control by
SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2}


def _stats(rows: list[dict[str, Any]]) -> dict[str, Any]:
    done = [r for r in rows if r["status"] == "CLOSED" and r.get("pnl_pct") is not None]
    n = len(done)
    return {"n": n, "avg_return_pct": round(sum(r["pnl_pct"] for r in done) / n, 1) if n else None,
            "win_rate_pct": round(sum(r["pnl"] > 0 for r in done) / n * 100, 1) if n else None,
            "pnl": round(sum(r["pnl"] for r in done), 2)}


def lane_table(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by: dict[str, list[dict[str, Any]]] = {}
    labels: dict[str, str] = {}
    for r in rows:
        by.setdefault(r["source"], []).append(r)
        labels[r["source"]] = r["source_label"]
    return sorted(({"source": s, "label": labels[s], **_stats(rs), "open": sum(1 for r in rs if r["status"] != "CLOSED")} for s, rs in by.items()),
                  key=lambda x: (-x["n"], x["label"]))


def _item(oid: str, severity: str, title: str, evidence: str, why: str, would_change: str) -> dict[str, Any]:
    return {"id": oid, "severity": severity, "title": title, "evidence": evidence, "why_it_matters": why, "would_change_my_mind": would_change}


def build(rows: list[dict[str, Any]], tracker: dict[str, Any], clock: dict[str, Any], challenge: Optional[dict[str, Any]],
          fictional: bool, as_of: str) -> dict[str, Any]:
    lanes = lane_table(rows)
    out: list[dict[str, Any]] = []
    if fictional:
        out.append(_item("fictional", "high", "Every number here comes from invented data",
                         "The data source is the built-in demo, not a market.", "Paper results on synthetic prices prove nothing about any strategy.",
                         "Running on real quotes for long enough to fill the sample-size gaps below."))
    behind = (clock or {}).get("behind_s")
    if behind is not None and behind > (clock or {}).get("tolerance_s", 5):
        out.append(_item("clock", "high", "This computer's clock is behind, so trades are being starved",
                         f"The clock is {behind:.0f}s behind the data, over the {clock.get('tolerance_s', 5):.0f}s limit.",
                         "Snapshots are rejected, so lanes that look idle or unlucky may simply not have been allowed to trade.",
                         "A synced clock and several days of normal entry counts."))
    small = [x for x in lanes if x["n"] < MIN_N]
    if not any(x["n"] for x in lanes):
        out.append(_item("sample", "high", "Nothing has closed yet, so there is nothing to judge",
                         "No account or lane has a closed trade.", "Every number on this page is a placeholder until trades have opened and closed.",
                         f"At least {MIN_N} closed trades in a lane."))
    elif small:
        out.append(_item("sample", "high" if len(small) == len(lanes) else "medium", "Most lanes have too few closed trades to rank",
                         f"{len(small)} of {len(lanes)} accounts and lanes have under {MIN_N} closed trades"
                         + (f" (for example {small[0]['label']}: {small[0]['n']})." if small else "."),
                         "With this few trades a strong or weak average is mostly luck, so any leaderboard built from it is a story.",
                         f"At least {MIN_N} closed trades in a lane, and the same ranking holding in a later, separate period."))
    ctl = next((x for x in lanes if x["source"] == CONTROL_LANE), None)
    rule = next((x for x in lanes if x["source"] == RULE_LANE), None)
    if ctl is None or ctl["n"] < MIN_N or rule is None or rule["n"] < MIN_N:
        have = f"The random control has {ctl['n'] if ctl else 0} closed trades and the pullback rule has {rule['n'] if rule else 0}."
        out.append(_item("control", "medium", "Nothing has been compared with a coin flip yet",
                         have, "A rule only means something if it beats picking names at random with the same exits and fees. Until both have "
                               f"{MIN_N} closed trades, 'the pullback rule works' is not a claim this platform can make.",
                         f"{MIN_N} closed trades in both lanes, with the rule leading the control by {BEAT_MARGIN_PTS:g}+ points of average return."))
    else:
        gap = rule["avg_return_pct"] - ctl["avg_return_pct"]
        if gap < BEAT_MARGIN_PTS:
            out.append(_item("control", "high", "The pullback rule does not beat random picks",
                             f"Pullback rule {rule['avg_return_pct']:+.1f}% over {rule['n']} trades against random control {ctl['avg_return_pct']:+.1f}% over {ctl['n']}.",
                             "If random picks with the same exits do as well, the rule's results are the exits and the market, not the signal.",
                             f"The rule leading the control by {BEAT_MARGIN_PTS:g}+ points over more trades."))
        else:
            out.append(_item("control", "low", "The pullback rule leads random picks, which is still not proof",
                             f"Rule {rule['avg_return_pct']:+.1f}% against control {ctl['avg_return_pct']:+.1f}% ({rule['n']} and {ctl['n']} trades).",
                             "Trades overlap in time and in names, one market regime can carry both, and this was one test among many lanes.",
                             "The lead surviving a later period it was not tuned on."))
    ranked = [x for x in lanes if x["n"] >= MIN_N and x["source"] != CONTROL_LANE]
    if len(lanes) >= 4 and ranked:
        best = max(ranked, key=lambda x: x["avg_return_pct"])
        out.append(_item("best_of_many", "medium", "The best lane is the best of many, so it will look good by chance",
                         f"{len(lanes)} lanes are running; {best['label']} leads at {best['avg_return_pct']:+.1f}% over {best['n']} trades.",
                         "Pick the winner after the fact from this many tries and the winner is flattered by selection alone.",
                         "Naming the winner in advance and watching it in a period it was not chosen from."))
    marks = int((tracker or {}).get("total_marks") or 0)
    if marks < int((tracker or {}).get("min_n") or MIN_N):
        out.append(_item("tracker", "low", "The unusual-flow tracker has too few marks to say anything",
                         f"{marks} marks so far; a group needs {(tracker or {}).get('min_n', MIN_N)} to be read.",
                         "Whether big options volume predicts anything is exactly what this tracker is for, and it cannot answer yet.",
                         "Several weeks of daily scans, with marks on the same name and day counted as one."))
    if challenge:
        done = int(challenge.get("attempts_finished") or 0)
        reached = int((challenge.get("outcomes") or {}).get("TARGET", 0))
        if done >= 1:
            out.append(_item("challenge", "medium", "The 10x challenge is a lottery with restarts",
                             f"{reached} of {done} finished attempts reached 10x.",
                             "Restarting after a wipe-out and quoting the best run is survivorship. Only the count of all attempts means anything.",
                             "A success rate across many attempts that is clearly above what the same sizing gives on random picks."))
    out.sort(key=lambda o: SEVERITY_ORDER[o["severity"]])
    return {"fictional": fictional, "as_of": as_of, "objections": out, "lanes": lanes, "min_n": MIN_N,
            "note": ("These are the platform arguing with its own numbers, computed from the records. "
                     "A missing objection is not evidence of an edge. Nothing here changes a limit or places an order.")}
