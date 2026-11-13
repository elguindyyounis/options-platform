"""What the platform has learned over time, and whether it is getting better, with the sample sizes beside every claim.

Everything here is read from records the platform already keeps: closed trades from every account and lane, the
agents' learned weights, the post-mortem causes, the options tracker's marks, the committee's mistakes and the 10x
challenge attempts. It adds no new trading rule. The "are we improving" check is deliberately blunt: it splits the
closed trades into an older half and a newer half and only calls a change real when both halves are large enough
and the gap is large. Strategy settings change as the platform is edited, so a better newer half is a lead, not proof.
"""
from __future__ import annotations

from typing import Any

MIN_HALF = 20            # closed trades each half needs before any verdict
MIN_GAP_PCT = 5.0        # points of average return (and of win rate) before the gap is called a change


def improvement(rows: list[dict[str, Any]]) -> dict[str, Any]:
    done = sorted((r for r in rows if r["status"] == "CLOSED" and r.get("pnl_pct") is not None and r.get("closed_at")), key=lambda r: r["closed_at"])
    out: dict[str, Any] = {"closed_trades": len(done), "min_half": MIN_HALF, "older": None, "newer": None}

    def stats(xs: list[dict[str, Any]]) -> dict[str, Any]:
        n = len(xs)
        return {"n": n, "from": xs[0]["closed_at"], "to": xs[-1]["closed_at"], "win_rate_pct": round(sum(r["pnl"] > 0 for r in xs) / n * 100, 1),
                "avg_return_pct": round(sum(r["pnl_pct"] for r in xs) / n, 1)}

    if len(done) < 2 * MIN_HALF:
        out["verdict"] = "TOO_EARLY"
        out["text"] = f"Too early to say. {len(done)} trades have closed; comparing an older and a newer half needs at least {2 * MIN_HALF} ({MIN_HALF} in each)."
        return out
    mid = len(done) // 2
    older, newer = stats(done[:mid]), stats(done[mid:])
    out["older"], out["newer"] = older, newer
    d_ret, d_win = newer["avg_return_pct"] - older["avg_return_pct"], newer["win_rate_pct"] - older["win_rate_pct"]
    out["change_return_pts"], out["change_win_rate_pts"] = round(d_ret, 1), round(d_win, 1)
    if d_ret >= MIN_GAP_PCT and d_win >= MIN_GAP_PCT:
        out["verdict"], word = "IMPROVING", "better than"
    elif d_ret <= -MIN_GAP_PCT and d_win <= -MIN_GAP_PCT:
        out["verdict"], word = "WORSENING", "worse than"
    else:
        out["verdict"], word = "NO_CLEAR_CHANGE", "about the same as"
    out["text"] = (f"The newer {newer['n']} closed trades are {word} the older {older['n']}: average return {newer['avg_return_pct']:+.1f}% against "
                   f"{older['avg_return_pct']:+.1f}%, winners {newer['win_rate_pct']:.0f}% against {older['win_rate_pct']:.0f}%.")
    return out


def milestones(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    done = sorted((r for r in rows if r["status"] == "CLOSED" and r.get("closed_at")), key=lambda r: r["closed_at"])
    marks = []
    for n in (1, 10, 25, 50, 100, 250, 500, 1000):
        if len(done) >= n:
            marks.append({"ts": done[n - 1]["closed_at"], "kind": "trades", "text": "Closed trade number " + str(n) + (" (first result to learn from)" if n == 1 else "")})
    return marks


def build(rows: list[dict[str, Any]], weights_history: list[dict[str, Any]], committee: dict[str, Any], digest: dict[str, Any],
          tracker: dict[str, Any], challenge: dict[str, Any], hypotheses: list[dict[str, Any]], fictional: bool, as_of: str) -> dict[str, Any]:
    imp = improvement(rows)
    timeline = milestones(rows)
    for w in weights_history:
        timeline.append({"ts": w["ts"], "kind": "agent", "text": f"{w['agent']}: {w['note']}"})
    for h in challenge.get("history", []):
        timeline.append({"ts": h["ended_at"], "kind": "challenge", "text": f"10x challenge attempt {h['attempt']} ended: {h['outcome'].lower().replace('_', ' ')} at {h['multiple']}x"})
    timeline.sort(key=lambda e: e["ts"], reverse=True)

    lessons: list[dict[str, Any]] = []
    for t in digest.get("tags", []):
        lessons.append({"source": "Post-mortems of closed trades", "text": f"{t['means']} Seen in {t['count']} trade{'s' if t['count'] != 1 else ''}, average {t['avg_net_pct']:+.1f}%. Next: {t['try_next']}",
                        "strength": "Pattern" if t["pattern"] else "Anecdote (too few trades)"})
    for text in committee.get("lessons", []):
        lessons.append({"source": "Agent committee mistakes", "text": text, "strength": "Anecdote (one trade)"})
    for text in tracker.get("findings", []):
        lessons.append({"source": "Options tracker", "text": text, "strength": "Lead to test (enough marks, not proof)"})
    for h in hypotheses:
        lessons.append({"source": "Registered experiments", "text": f"{h['id']}: {h['statement']} Status: {h['status'].lower().replace('_', ' ')}.", "strength": "Pre-registered"})
    ch = challenge.get("attempts_finished", 0)
    if ch:
        lessons.append({"source": "10x challenge", "text": challenge.get("honesty", ""), "strength": "Selection bias: counts every try"})

    agents = []
    for name, a in sorted((committee.get("agents") or {}).items()):
        votes = a.get("votes", {})
        n = sum(v["n"] for v in votes.values())
        agents.append({"agent": name, "weight": a.get("weight"), "outcomes": n, "descriptive_only": a.get("descriptive_only", True)})

    summary = [imp["text"]]
    cm = committee.get("committee", {})
    enter = cm.get("WOULD_ENTER", {})
    if enter.get("n"):
        summary.append(f"The committee has seen {enter['n']} of its entries play out; {round((enter['hit_rate'] or 0) * 100)}% were profitable after {committee.get('horizon_hours')} hours.")
    summary.append(f"{tracker.get('total_marks', 0)} option-flow marks and {len(rows)} trades across all lanes are on record"
                   + (f"; {ch} challenge attempts have finished." if ch else "."))
    return {"fictional": fictional, "as_of": as_of, "improvement": imp, "summary": summary, "timeline": timeline[:60], "lessons": lessons, "agents": agents,
            "counts": {"trades": len(rows), "closed": imp["closed_trades"], "tracker_marks": tracker.get("total_marks", 0), "lessons": len(lessons),
                       "weight_changes": len(weights_history)},
            "caveat": "Settings, lanes and thresholds change as the platform is edited, so a later period doing better is a lead, not proof of learning. "
                      "Paper results on demo data prove nothing, and nothing here claims an edge."}
