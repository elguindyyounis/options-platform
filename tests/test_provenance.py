from optplat import signals
from optplat.provenance import PROVENANCE, provenance


def test_every_computed_signal_has_a_provenance_entry():
    ids = {p["id"] for p in PROVENANCE}
    assert set(signals.SIGNAL_NAMES) <= ids


def test_ids_are_unique_and_each_entry_states_a_caveat_and_origin():
    ids = [p["id"] for p in PROVENANCE]
    assert len(ids) == len(set(ids))
    for p in PROVENANCE:
        assert p["caveat"].strip() and p["definition"].strip()
        assert p["origin"] in {"HEURISTIC", "STANDARD_MODEL", "INFERENCE"}


def test_nothing_is_validated_unless_the_owner_listed_it(monkeypatch):
    out = provenance()
    assert all(r["validation"] == "UNVALIDATED" for r in out["signals"]) and out["unvalidated"] == len(PROVENANCE)
    monkeypatch.setattr("optplat.provenance.VALIDATED_SIGNALS", frozenset({"gex_total"}))
    rows = {r["id"]: r["validation"] for r in provenance()["signals"]}
    assert rows["gex_total"] == "VALIDATED" and rows["unusual_count"] == "UNVALIDATED"


def test_inferences_are_flagged_as_guesses():
    inf = {p["id"] for p in PROVENANCE if p["origin"] == "INFERENCE"}
    assert {"likely_side", "open_or_close"} <= inf
