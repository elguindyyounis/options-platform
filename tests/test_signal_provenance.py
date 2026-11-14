"""The provenance page must list every signal and lane, and must not claim more than the code allows."""
from __future__ import annotations

import re
from pathlib import Path

from optplat import optionlanes, signals

DOC = (Path(__file__).resolve().parents[1] / "docs" / "SIGNAL_PROVENANCE.md").read_text()
ROWS = [[c.strip() for c in line.strip().strip("|").split("|")] for line in DOC.splitlines() if line.startswith("| `")]
STATUSES = {"UNVALIDATED", "STUDY_ONLY", "VALIDATED"}


def _row(name: str) -> list[str]:
    hits = [r for r in ROWS if r[0] == f"`{name}`"]
    assert len(hits) == 1, f"{name} must appear exactly once as a table row start"
    return hits[0]


def test_every_signal_is_listed_with_matching_status():
    for name in signals.SIGNAL_NAMES:
        status = _row(name)[3]
        assert status in STATUSES
        assert (status == "VALIDATED") == (name in signals.VALIDATED_SIGNALS), name


def test_every_lane_is_listed_and_none_claims_validation():
    for p in optionlanes.ALL_PARAMS:
        status = _row(p.lane)[3]
        assert status in STATUSES
        assert status != "VALIDATED", f"{p.lane}: an agent must not mark a lane validated"


def test_every_row_has_a_caveat_and_a_known_status():
    for r in ROWS:
        assert r[-1], f"row {r[0]} has no caveat"
        assert any(c in STATUSES for c in r), f"row {r[0]} has no status"


def test_page_makes_no_edge_claim():
    assert not re.search(r"\b(proven|has an edge|profitable)\b", DOC, re.I)
