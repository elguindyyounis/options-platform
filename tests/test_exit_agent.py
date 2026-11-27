from helpers import CONTRACT, NOW, make_quote
from optplat import exit_agent as ea
from optplat.exits import EXIT, HOLD, TRIM, ExitPolicy
from optplat.models import Position, Right

POLICY = ExitPolicy()
UP = [100 + i * 0.5 for i in range(40)]            # steady uptrend: supports a call
DOWN = [120 - i * 0.5 for i in range(40)]          # steady slide: against a call


def call(qty=4, cost=2.00):
    assert CONTRACT.right is Right.CALL
    return Position(CONTRACT, qty, cost)


def run(bid, closes, qty=4, trimmed=False, policy=POLICY):
    return ea.decide(call(qty), make_quote(bid, bid + 0.05), closes, entry_time=None, now=NOW, policy=policy, trimmed=trimmed)


def test_a_winner_past_the_old_target_is_kept_while_the_trend_supports_it_and_trimmed_when_it_is_big():
    d = run(2.90, UP, qty=1)                        # +45%, one contract: cannot trim, trend strong -> hold past the 40% target
    assert d.action == HOLD and "Keep holding" in d.reason
    t = run(2.90, UP, qty=4)                        # +45% with 4 contracts: bank half, keep the rest
    assert (t.action, t.trigger) == (TRIM, "agent_trim")


def test_a_gain_past_target_without_support_is_taken_and_a_broken_trend_exits_early():
    flat = [100.0] * 40
    assert run(2.90, flat, qty=1).trigger == "agent_take_profit"            # neutral evidence: the old target applies
    d = run(2.30, DOWN)                                                      # +15%, trend broken
    assert (d.action, d.trigger) == (EXIT, "agent_thesis_broken")
    loser = run(1.70, DOWN)                                                  # -15%: cut before the 30% stop
    assert (loser.action, loser.trigger) == (EXIT, "agent_thesis_broken")


def test_floors_the_agent_cannot_override():
    assert run(1.30, UP).trigger == "stop_loss"                              # 30% stop stands even in an uptrend
    assert run(2.90, UP, trimmed=True).action == HOLD                        # rest of a trim keeps running
    assert run(1.95, UP, trimmed=True).trigger == "stop_to_entry"            # and stops at entry
    assert ea.decide(call(), None, UP, entry_time=None, now=NOW, policy=POLICY).action == "UNOBSERVABLE"


def test_no_evidence_means_the_old_fixed_rules():
    assert run(2.90, UP[:10], qty=4).trigger == "take_profit"                # too few closes: plain 40% target, no trim, no holding on
    assert ea.decide(call(), make_quote(2.90, 2.95), None, entry_time=None, now=NOW, policy=POLICY).trigger == "take_profit"


def test_a_put_reads_the_trend_the_other_way():
    from datetime import date
    from optplat.models import OptionContract
    put = Position(OptionContract(CONTRACT.underlying, CONTRACT.expiry, Right.PUT, CONTRACT.strike), 1, 2.00)
    h_up = ea.hold_evidence(put, make_quote(2.30, 2.35), UP)[0]
    h_down = ea.hold_evidence(put, make_quote(2.30, 2.35), DOWN)[0]
    assert h_down > 0.5 > h_up
