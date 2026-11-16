from datetime import timedelta

import pytest

from helpers import NOW
from optplat.store import Store
from optplat.weekly import MIN_REJECTIONS_FOR_PATTERN, build_report, format_report, main, propose
from test_engine import build

BASE = {"data_issues": {}, "rejection_reasons": {}, "forward_returns": {}}


def test_report_on_a_fresh_store_is_honest_and_does_not_crash():
    r = build_report(Store(":memory:"), NOW)
    text = format_report(r)
    assert "Not enough equity points" in text and "None recorded" in text and "No ranking question yet" in text
    assert "edge" in text  # the standing caveat is always present


def test_report_counts_only_the_period_and_keeps_fictional_apart():
    engine, manager, _, _, clock = build(auto_entries=True)
    engine.run_cycle()
    store = manager.store
    assert build_report(store, NOW, include_fictional=True)["decisions"].get("ENTRY:FILLED") == 1
    assert build_report(store, NOW + timedelta(days=30), days=7, include_fictional=True)["decisions"] == {}


def test_data_issues_are_proposed_first():
    out = propose({**BASE, "data_issues": {"FROZEN_QUOTES": {"items": 40, "severity": "warn"}}})
    assert out[0]["title"].startswith("Fix data reliability")


def test_a_dominant_rejection_rule_is_flagged_without_telling_anyone_to_loosen_it():
    reasons = {"max_open_premium exceeded": MIN_REJECTIONS_FOR_PATTERN, "other": 2}
    out = propose({**BASE, "rejection_reasons": reasons})
    p = next(x for x in out if "risk rule" in x["title"])
    assert "must not loosen" in p["next"] and "max_open_premium" in p["evidence"]


def test_few_rejections_are_noise_not_a_pattern():
    assert not any("risk rule" in p["title"] for p in propose({**BASE, "rejection_reasons": {"x": 5}}))


def _fwd(chosen, passed, n=30):
    cell = lambda mean: {"24h": {"matured": n, "pending": 0, "unobservable": 0, "mean_return_pct": mean, "descriptive_only": False}}
    return {"FILLED": cell(chosen), "NOT_CHOSEN": cell(passed)}


def test_ranking_question_needs_enough_samples_and_a_real_gap():
    assert any("ranking picking worse" in p["title"] for p in propose({**BASE, "forward_returns": _fwd(1.0, 5.0)}))
    assert not any("ranking picking worse" in p["title"] for p in propose({**BASE, "forward_returns": _fwd(1.0, 1.5)}))
    assert not any("ranking picking worse" in p["title"] for p in propose({**BASE, "forward_returns": _fwd(1.0, 5.0, n=29)}))


def test_cli_reads_read_only_and_writes_a_file(tmp_path, capsys):
    db = tmp_path / "w.db"
    Store(str(db)).close() if hasattr(Store, "close") else Store(str(db))
    out = tmp_path / "r.md"
    assert main(["--db", str(db), "--out", str(out)]) == 0
    assert out.read_text().startswith("# Weekly research report")
    assert main(["--db", str(tmp_path / "missing.db")]) == 1
    assert main(["--db", str(db), "--days", "0"]) == 1
