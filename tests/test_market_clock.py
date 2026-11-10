from datetime import datetime, timezone

import pytest

from optplat.market_clock import is_open, session_status


def utc(*args):
    return datetime(*args, tzinfo=timezone.utc)


def test_regular_session_open_in_winter_time():
    assert session_status(utc(2026, 11, 16, 15, 0)) == (True, "Regular session")  # 10:00 EST Monday


def test_open_and_close_boundaries_in_winter():
    assert not is_open(utc(2026, 11, 16, 14, 29))  # 09:29 EST
    assert is_open(utc(2026, 11, 16, 14, 30))      # 09:30 EST
    assert is_open(utc(2026, 11, 16, 20, 59))      # 15:59 EST
    assert not is_open(utc(2026, 11, 16, 21, 0))   # 16:00 EST


def test_daylight_saving_shifts_the_utc_boundaries():
    assert not is_open(utc(2026, 7, 15, 13, 29))   # 09:29 EDT
    assert is_open(utc(2026, 7, 15, 13, 30))       # 09:30 EDT


def test_weekend_is_closed():
    assert session_status(utc(2026, 11, 14, 15, 0)) == (False, "Weekend")


def test_holidays_are_closed():
    assert session_status(utc(2026, 11, 26, 15, 0)) == (False, "Market holiday")  # Thanksgiving
    assert not is_open(utc(2026, 7, 3, 15, 0))                                     # Independence Day observed
    assert not is_open(utc(2026, 12, 25, 15, 0))


def test_early_close_after_thanksgiving():
    assert is_open(utc(2026, 11, 27, 17, 59))      # 12:59 EST
    assert not is_open(utc(2026, 11, 27, 18, 0))   # 13:00 EST
    assert "early close" in session_status(utc(2026, 11, 27, 15, 0))[1]


def test_unknown_year_fails_closed():
    open_, reason = session_status(utc(2027, 3, 3, 15, 0))
    assert open_ is False and "2027" in reason


def test_naive_datetime_is_rejected():
    with pytest.raises(ValueError):
        session_status(datetime(2026, 11, 16, 15, 0))
