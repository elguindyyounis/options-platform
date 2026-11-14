"""The provenance doc must list every signal and cause tag, with a status that matches the code."""
import re
from pathlib import Path

from optplat import signals
from optplat.postmortem import CAUSES

DOC = (Path(__file__).resolve().parents[1] / "docs" / "SIGNALS.md").read_text()


def _signal_rows() -> dict[str, str]:
    rows = {}
    for line in DOC.splitlines():
        m = re.match(r"\|\s*`(\w+)`\s*\|(.*)\|\s*(UNVALIDATED|VALIDATED)\s*\|[^|]*\|\s*$", line)
        if m:
            rows[m.group(1)] = m.group(3)
    return rows


def test_every_signal_has_a_row_and_matching_status():
    rows = _signal_rows()
    for name in signals.SIGNAL_NAMES:
        assert name in rows, f"{name} missing from docs/SIGNALS.md"
        expected = "VALIDATED" if name in signals.VALIDATED_SIGNALS else "UNVALIDATED"
        assert rows[name] == expected, f"{name} status in docs/SIGNALS.md disagrees with VALIDATED_SIGNALS"


def test_every_cause_tag_is_documented():
    for tag in CAUSES:
        assert f"`{tag}`" in DOC, f"post-mortem tag {tag} missing from docs/SIGNALS.md"


def test_inferred_labels_documented():
    for label in ("likely_side", "position_read", "flow_lean"):
        assert f"`{label}`" in DOC


def test_doc_makes_no_edge_claim():
    assert "No signal below has any validation" in DOC


def test_gex_row_states_the_sign_assumption():
    assert "gross" in DOC and "flips sign" in DOC
