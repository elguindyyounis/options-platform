from optplat.rotation import build, by_day


def scan(day, sectors, calls=None):
    return {"session_day": day, "heat_map": {"sectors": [{"sector": k, "dollar_volume": v[0], "avg_change_pct": v[1], "avg_relative_volume": 1.0} for k, v in sectors.items()]},
            "option_names": calls or []}


def test_the_newest_scan_of_each_day_is_used_and_scans_without_a_heat_map_are_skipped():
    a, b = scan("2026-11-10", {"X": (1, 0)}), scan("2026-11-10", {"X": (2, 0)})
    assert by_day([a, b, {"session_day": "2026-11-11"}, {"session_day": "2026-11-11", "heat_map": {"sectors": []}}]) == [b]


def test_one_day_is_not_enough_to_call_a_rotation():
    out = build([scan("2026-11-10", {"Tech": (60, 1.0), "Energy": (40, -1.0)})], True)
    assert not out["ready"] and "at least 2" in out["summary"][0] and out["sectors"][0]["share_pct"] in (60.0, 40.0)
    assert build([], True)["sectors"] == []


def test_shares_changes_and_compounded_moves_are_computed_across_days():
    scans = [scan("2026-11-10", {"Tech": (60, 1.0), "Energy": (40, -1.0)}), scan("2026-11-11", {"Tech": (50, 2.0), "Energy": (50, 1.0)}),
             scan("2026-11-12", {"Tech": (40, 0.0), "Energy": (60, 1.0)}, calls=[{"sector": "Energy", "call_volume": 300, "put_volume": 100}])]
    out = build(scans, False)
    by = {x["sector"]: x for x in out["sectors"]}
    assert out["ready"] and out["days"] == ["2026-11-10", "2026-11-11", "2026-11-12"]
    assert by["Energy"]["share_change_pts"] == 20.0 and by["Energy"]["trend"] == "GAINING" and by["Tech"]["trend"] == "LOSING"
    assert by["Tech"]["share_change_1d_pts"] == -10.0 and by["Energy"]["call_put_ratio"] == 3.0 and by["Tech"]["call_put_ratio"] is None
    assert by["Tech"]["cumulative_change_pct"] == round((1.01 * 1.02 * 1.0 - 1) * 100, 2)
    assert out["sectors"][0]["sector"] == "Energy" and "Energy" in out["summary"][0] and "Tech" in out["summary"][1]
    assert by["Tech"]["history"] == [60.0, 50.0, 40.0]


def test_small_shifts_are_called_steady_and_a_sector_missing_a_day_keeps_a_gap():
    scans = [scan("2026-11-10", {"A": (50, 0), "B": (50, 0)}), scan("2026-11-11", {"A": (50.2, 0), "B": (49.8, 0), "C": (0.0001, 0)})]
    out = build(scans, True)
    by = {x["sector"]: x for x in out["sectors"]}
    assert by["A"]["trend"] == "STEADY" and "steady" in out["summary"][0]
    assert by["C"]["history"][0] is None and by["C"]["days_seen"] == 1
