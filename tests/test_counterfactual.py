from datetime import timedelta

from optplat.counterfactual import MIN_RESOLVED, CounterfactualJournal, hypothetical_return_pct
from optplat.models import Quote
from optplat.store import Store

from helpers import CONTRACT, NOW, make_quote

KEY = CONTRACT.occ_symbol


def journal():
    return CounterfactualJournal(Store(":memory:"))


def later(days, bid=2.2, ask=2.3):
    return Quote(CONTRACT, bid, ask, NOW + timedelta(days=days, hours=1), "test")


def test_return_includes_slippage_both_ways():
    assert hypothetical_return_pct(2.0, 2.0, 0.0) == 0.0
    assert hypothetical_return_pct(2.0, 2.0, 0.5) < 0  # round trip costs money even when flat
    assert hypothetical_return_pct(2.0, 3.0, 0.0) == 50.0


def test_unusable_inputs_return_none():
    for args in [(0, 1), (-1, 1), (2, -1), (float("nan"), 1), (2, float("inf")), (True, 1)]:
        assert hypothetical_return_pct(*args) is None
    assert hypothetical_return_pct(2, 1, slippage_pct=50) is None


def test_record_makes_one_case_per_horizon_and_is_idempotent():
    j = journal()
    assert j.record(setup_id="s1", contract_key=KEY, decision="REJECTED", reason="wide spread",
                    quote=make_quote(), now=NOW) == 3
    assert j.record(setup_id="s1", contract_key=KEY, decision="REJECTED", reason="wide spread",
                    quote=make_quote(), now=NOW) == 0


def test_refuses_unknown_decision_and_invalid_quote():
    j = journal()
    assert j.record(setup_id="s", contract_key=KEY, decision="BOUGHT", reason="", quote=make_quote(), now=NOW) == 0
    bad = make_quote(bid=3.0, ask=2.0)
    assert j.record(setup_id="s", contract_key=KEY, decision="REJECTED", reason="", quote=bad, now=NOW) == 0


def test_same_session_quote_cannot_resolve_a_case():
    j = journal()
    j.record(setup_id="s1", contract_key=KEY, decision="REJECTED", reason="r", quote=make_quote(), now=NOW)
    early = Quote(CONTRACT, 2.2, 2.3, NOW + timedelta(hours=1), "test")  # inside MIN_GAP
    res = j.mark({KEY: early}, now=NOW + timedelta(days=1, minutes=1))
    assert res == {"evaluated": 0, "no_data": 0}  # stays pending, not scored


def test_resolution_and_no_data_after_grace():
    j = journal()
    j.record(setup_id="s1", contract_key=KEY, decision="REJECTED", reason="r", quote=make_quote(), now=NOW)
    res = j.mark({KEY: later(1)}, now=NOW + timedelta(days=1, hours=2))
    assert res["evaluated"] == 1
    # 7d and 30d horizons have no quote: pending until grace passes, then NO_DATA (counted, not dropped)
    res = j.mark({}, now=NOW + timedelta(days=60))
    assert res["no_data"] == 2
    row = {(r["decision"], r["horizon_days"]): r for r in j.summary()["rows"]}
    assert row[("REJECTED", 7)]["no_data"] == 1 and row[("REJECTED", 7)]["unresolved_share_pct"] == 100.0


def test_summary_withholds_numbers_below_sample_gate_then_reports():
    j = journal()
    for i in range(MIN_RESOLVED - 1):
        j.record(setup_id=f"s{i}", contract_key=KEY, decision="NOT_SELECTED", reason="r",
                 quote=make_quote(), now=NOW)
    j.mark({KEY: later(2)}, now=NOW + timedelta(days=2))
    r = [x for x in j.summary()["rows"] if x["horizon_days"] == 1][0]
    assert r["resolved"] == MIN_RESOLVED - 1 and not r["sample_sufficient"]
    assert r["mean_return_pct"] is None and r["median_return_pct"] is None
    j.record(setup_id="last", contract_key=KEY, decision="NOT_SELECTED", reason="r", quote=make_quote(), now=NOW)
    j.mark({KEY: later(2)}, now=NOW + timedelta(days=2))
    r = [x for x in j.summary()["rows"] if x["horizon_days"] == 1][0]
    assert r["sample_sufficient"] and r["mean_return_pct"] is not None


def test_summary_carries_not_a_result_note():
    assert "Not fills" in journal().summary()["note"]
