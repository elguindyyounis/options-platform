import math

from helpers import CONTRACT, make_quote
from optplat.models import Position
from optplat.stress import exit_stress, spread_concession_pct

POS = Position(CONTRACT, 2, 2.00)


def by_label(result):
    return {s["scenario"]: s for s in result["scenarios"]}


def test_tight_market_has_no_extra_concession():
    r = exit_stress(POS, make_quote(2.00, 2.05))
    s = by_label(r)
    assert s["WIDE_MARKET"]["extra_concession_pct"] == 0.0
    assert s["WIDE_MARKET"]["pnl_usd"] == s["SIM_FILL"]["pnl_usd"]


def test_scenarios_get_monotonically_worse_in_wide_market():
    r = exit_stress(POS, make_quote(2.00, 3.00))  # 33% spread
    s = by_label(r)
    assert s["SIM_FILL"]["pnl_usd"] > s["WIDE_MARKET"]["pnl_usd"] > s["STRESSED_EXIT"]["pnl_usd"]
    assert s["WIDE_MARKET"]["extra_concession_pct"] > 0


def test_sim_fill_matches_broker_formula():
    r = exit_stress(POS, make_quote(3.00, 3.10), slippage_pct=0.5)
    # 3.00 * 0.995 = 2.985 -> proceeds 597.00 vs cost 400.00
    assert by_label(r)["SIM_FILL"]["pnl_usd"] == round(2.985 * 100 * 2 - 400, 2)


def test_concession_is_capped_and_nonfinite_fails_closed():
    assert spread_concession_pct(500) == 65.0
    assert spread_concession_pct(math.nan) == 65.0
    assert spread_concession_pct(3) == 0.0


def test_invalid_quote_or_basis_is_unavailable():
    assert exit_stress(POS, make_quote(3.0, 2.0))["available"] is False
    assert exit_stress(Position(CONTRACT, 2, 0.0), make_quote(2.0, 2.1))["available"] is False
    assert exit_stress(Position(CONTRACT, 0, 2.0), make_quote(2.0, 2.1))["available"] is False
