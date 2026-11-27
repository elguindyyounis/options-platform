"""On IBKR data a lane fills only at IBKR's verified quote for the one contract it picked (owner decision 2026-11-27)."""
import json
from dataclasses import replace

from optplat import optionlanes as ol
from optplat.ibkr_data import VERIFIED_SOURCE
from optplat.models import Quote
from optplat.store import Store
from test_optionlanes import OptFeed, opened, uptrend

IBKR = "ibkr-shared-research-only"


class IBKRNoCheck(OptFeed):
    """Demo chains relabelled as unverified IBKR and live unverified marks, with NO way to verify one contract."""
    execution_veto = True

    def __init__(self, clock, daily, verify):
        super().__init__(clock, daily=daily)
        self.verify, self.asked = verify, []

    def snapshot_window(self, symbol, *a, **k):
        return replace(super().snapshot_window(symbol, *a, **k), source=IBKR, timestamp_verified=False)

    def quotes_for(self, contracts):
        return []                                            # never executable marks from IBKR

    def decision_quotes_for(self, contracts):
        return [replace(q, source="ibkr", timestamp_verified=False) for q in OptFeed.quotes_for(self, contracts)]


class IBKRLike(IBKRNoCheck):
    """The same, plus a switchable verified quote for one contract."""
    def execution_quote(self, contract):
        self.asked.append(contract)
        return self.verify(contract)


def verified(bid, ask, clock):
    return lambda c: Quote(c, bid, ask, clock(), VERIFIED_SOURCE, timestamp_verified=True)


def lane_on_ibkr(verify_factory, cls=None):
    data, now = uptrend()
    box = [now]
    clock = lambda: box[0]                                   # noqa: E731
    prov = (cls or IBKRLike)(clock, data, None)
    prov.verify = verify_factory(clock)
    store = Store(":memory:")
    lane = ol.OptionLane(prov, store, replace(ol.SWING_AGGR, symbols=("AAPL",), budget_usd=20000.0),
                         ol.Feed(prov, clock), clock=clock)
    return lane, prov, store, box


def test_entry_fills_at_the_verified_quote_not_the_chain():
    lane, prov, store, box = lane_on_ibkr(lambda clock: verified(4.00, 4.20, clock))
    out = lane.step(force=True)
    t = opened(lane, prov, store)
    assert len(t) == 1 and t[0]["entry_price"] == 4.20
    o = t[0]["open_payload"]
    assert o["quote_verified"] is True and o["ask"] == 4.20 and "chain_ask" in o
    assert len(prov.asked) == 1 and out["verifications"][0]["result"] == "VERIFIED"


def test_no_verification_means_no_trade():
    lane, prov, store, box = lane_on_ibkr(lambda clock: (lambda c: None))
    out = lane.step(force=True)
    assert opened(lane, prov, store) == [] and any("could not verify" in s for s in out["skips"])


def test_a_verified_quote_outside_the_lane_limits_is_refused():
    lane, prov, store, box = lane_on_ibkr(lambda clock: verified(1.00, 4.00, clock))   # 75% spread
    out = lane.step(force=True)
    assert opened(lane, prov, store) == [] and any("outside the lane" in s for s in out["skips"])


def test_an_unverified_quote_from_the_check_is_not_trusted():
    lane, prov, store, box = lane_on_ibkr(lambda clock: (lambda c: Quote(c, 4.0, 4.2, clock(), "ibkr", timestamp_verified=False)))
    lane.step(force=True)
    assert opened(lane, prov, store) == []


def test_without_an_execution_quote_method_ibkr_chains_still_never_open():
    lane, prov, store, box = lane_on_ibkr(lambda clock: verified(4.0, 4.2, clock), cls=IBKRNoCheck)
    lane.step(force=True)
    assert opened(lane, prov, store) == []


def test_exit_is_noticed_on_live_marks_and_closed_only_at_a_verified_bid():
    lane, prov, store, box = lane_on_ibkr(lambda clock: verified(4.00, 4.20, clock))
    lane.step(force=True)
    t = opened(lane, prov, store)[0]
    contract = t["open_payload"]["contract"]
    prov.override[contract] = (1.0, 1.1)                    # live mark far below the 50% stop
    prov.verify = lambda c: None                            # IBKR cannot verify right now
    out = lane.step(force=True)
    assert store.lane_trades(lane.p.lane, True, 3)[0]["closed_at"] is None
    assert any("could not verify a bid" in e for e in out["errors"])
    assert json.loads(store.get_state(f"lane_mark:{t['id']}"))["verified"] is False
    prov.verify = verified(1.05, 1.15, lane.clock)
    lane.step(force=True)
    done = store.lane_trades(lane.p.lane, True, 3)[0]
    assert done["close_reason"] == "stop" and done["exit_price"] == 1.05
    assert done["close_payload"]["quote_verified"] is True


def test_verifications_are_capped_per_check():
    lane, prov, store, box = lane_on_ibkr(lambda clock: (lambda c: None))
    out = {"errors": [], "skips": []}
    c = ol.OptionContract("AAPL", box[0].date(), ol.Right.CALL, 100.0)
    for _ in range(ol.VERIFY_PER_STEP + 2):
        lane._verify(c, out)
    assert len(prov.asked) == ol.VERIFY_PER_STEP
    assert out["verifications"][-1]["result"] == "BUDGET_SPENT_THIS_CHECK"


def test_pick_contract_still_refuses_unverified_ibkr_chains_by_default():
    lane, prov, store, box = lane_on_ibkr(lambda clock: verified(4.0, 4.2, clock))
    snap = prov.snapshot_window("AAPL", 14, 35, 3)
    assert ol.pick_contract(snap, ol.Right.CALL, box[0], lane.p) is None
    assert ol.pick_contract(snap, ol.Right.CALL, box[0], lane.p, verify_later=True) is not None


def test_a_challenge_attempt_does_not_end_while_ibkr_cannot_verify_a_close():
    import datetime as dt
    from optplat import challenge as ch
    from test_optionlanes import short_up
    bars, now = short_up()
    box = [now]
    clock = lambda: box[0]                                   # noqa: E731
    prov = IBKRLike(clock, bars, lambda c: None)            # live marks, but no verified quote
    store = Store(":memory:")
    lane = ch.ChallengeLane.__new__(ch.ChallengeLane)
    ol.OptionLane.__init__(lane, prov, store, replace(ch.CHALLENGE, symbols=("SPY",)), ol.Feed(prov, clock), clock=clock)
    lane._attempt = {}
    lane._load_attempt(now)
    c = prov.snapshot_window("SPY", 1, 60, 3).rows[0].contract
    store.lane_open(lane.p.lane, "SPY", now - dt.timedelta(days=1), 1.0, 1, True,
                    {"multiplier": 100, "fees_open": 0, "fee_per_contract": 0.65, "attempt": 1, "right": c.right.value,
                     "contract": c.occ_symbol, "expiry": c.expiry.isoformat(), "strike": c.strike})
    box[0] = now + dt.timedelta(days=31)
    prov.decision_quotes_for = lambda cs: [Quote(x, 1.0, 1.1, clock(), "ibkr", timestamp_verified=False) for x in cs]
    out = lane.step(force=True)
    assert store.get_state("challenge:history", "[]") == "[]"
    assert any("could not verify a bid" in e for e in out["errors"])
