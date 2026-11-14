"""Open positions are only marked on a quote that could plausibly be sold into (age and spread limits)."""
from datetime import timedelta

from optplat.marks import MAX_MARK_AGE_S, MAX_MARK_SPREAD_PCT, mark_from_quote

from helpers import NOW, make_quote


def test_a_fresh_tight_bid_is_the_mark():
    assert mark_from_quote(make_quote(1.90, 2.00), NOW) == (1.90, "BID")


def test_a_stale_quote_is_not_a_mark_even_with_a_good_bid():
    q = make_quote(1.90, 2.00)
    assert mark_from_quote(q, NOW + timedelta(seconds=MAX_MARK_AGE_S + 1)) == (None, "STALE")
    assert mark_from_quote(q, NOW + timedelta(seconds=MAX_MARK_AGE_S))[1] == "BID"


def test_a_quote_from_the_future_is_not_a_mark():
    assert mark_from_quote(make_quote(), NOW - timedelta(seconds=300)) == (None, "STALE")


def test_a_wide_spread_is_not_a_mark():
    wide = make_quote(1.00, 2.00)  # 50% of the ask
    assert wide.spread_pct_of_ask() > MAX_MARK_SPREAD_PCT
    assert mark_from_quote(wide, NOW) == (None, "WIDE_SPREAD")
    assert mark_from_quote(make_quote(1.30, 2.00), NOW)[1] == "BID"  # exactly 35% is allowed


def test_no_bid_or_a_crossed_quote_is_unobservable():
    assert mark_from_quote(make_quote(0.0, 2.00), NOW) == (None, "UNOBSERVABLE")
    assert mark_from_quote(make_quote(2.10, 2.00), NOW) == (None, "UNOBSERVABLE")
