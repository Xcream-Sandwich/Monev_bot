from datetime import datetime, date
from zoneinfo import ZoneInfo
from config import is_off_day, parse_time_str, is_user_allowed, WIB_TZ


def test_is_off_day():
    # 2026-09-26 is Saturday (off day)
    sat = datetime(2026, 9, 26, 12, 0, tzinfo=WIB_TZ)
    # 2026-09-27 is Sunday (off day)
    sun = datetime(2026, 9, 27, 12, 0, tzinfo=WIB_TZ)
    # 2026-09-28 is Monday (work day)
    mon = datetime(2026, 9, 28, 12, 0, tzinfo=WIB_TZ)

    assert is_off_day(sat) is True
    assert is_off_day(sun) is True
    assert is_off_day(mon) is False


def test_parse_time_str():
    t = parse_time_str("16:30")
    assert t.hour == 16
    assert t.minute == 30

    default_t = parse_time_str("invalid")
    assert default_t.hour == 16
    assert default_t.minute == 0


def test_is_user_allowed():
    # When whitelist empty, all allowed
    assert is_user_allowed(123456) is True
