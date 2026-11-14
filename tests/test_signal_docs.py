"""Keeps docs/SIGNALS.md in step with the code: a new signal, lane or agent needs a provenance row."""
from pathlib import Path

from optplat import agents, optionlanes, signals

DOC = (Path(__file__).resolve().parent.parent / "docs" / "SIGNALS.md").read_text()


def test_every_signal_name_is_documented():
    for name in signals.SIGNAL_NAMES:
        assert f"`{name}`" in DOC, name


def test_every_lane_is_documented():
    for p in optionlanes.ALL_PARAMS:
        assert f"`{p.lane}`" in DOC, p.lane


def test_every_committee_agent_is_documented():
    for fn in agents.ANALYSTS + agents.CHECKERS:
        assert f"`{fn.__name__}`" in DOC, fn.__name__


def test_doc_claims_nothing_is_validated():
    assert "Nothing in this file is `VALIDATED`" in DOC
    # if the owner ever validates a signal, this test fails on purpose: the doc must then be updated by a human.
    assert signals.VALIDATED_SIGNALS == frozenset()
