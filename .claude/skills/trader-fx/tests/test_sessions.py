import _path  # noqa
import unittest
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import sessions

NY = ZoneInfo("America/New_York")


def ny(y, m, d, hh, mm=0):
    return datetime(y, m, d, hh, mm, tzinfo=NY).astimezone(timezone.utc)


def utc(y, m, d, hh, mm=0):
    return datetime(y, m, d, hh, mm, tzinfo=timezone.utc)


def row(table, name):
    return next(r for r in table if r["name"] == name)


class MarketStateTest(unittest.TestCase):
    def test_market_state_boundaries(self):
        # 2026-11-13 is a Friday, 2026-11-14 Saturday, 2026-11-15 Sunday
        self.assertEqual(sessions.market_state(ny(2026, 11, 13, 16, 59)), "open")
        self.assertEqual(sessions.market_state(ny(2026, 11, 13, 17, 0)), "closed_weekend")
        self.assertEqual(sessions.market_state(ny(2026, 11, 14, 12, 0)), "closed_weekend")
        self.assertEqual(sessions.market_state(ny(2026, 11, 15, 16, 59)), "closed_weekend")
        self.assertEqual(sessions.market_state(ny(2026, 11, 15, 17, 0)), "open")

    def test_saturday_edges_and_midweek(self):
        self.assertEqual(sessions.market_state(ny(2026, 11, 14, 0, 0)), "closed_weekend")
        self.assertEqual(sessions.market_state(ny(2026, 11, 14, 23, 59)), "closed_weekend")
        self.assertEqual(sessions.market_state(ny(2026, 11, 16, 0, 0)), "open")
        self.assertEqual(sessions.market_state(ny(2026, 11, 11, 3, 0)), "open")

    def test_boundaries_hold_in_us_dst(self):
        # 2026-07-10 Friday, 2026-07-12 Sunday (New York on daylight time)
        self.assertEqual(sessions.market_state(ny(2026, 7, 10, 16, 59)), "open")
        self.assertEqual(sessions.market_state(ny(2026, 7, 10, 17, 0)), "closed_weekend")
        self.assertEqual(sessions.market_state(ny(2026, 7, 12, 16, 59)), "closed_weekend")
        self.assertEqual(sessions.market_state(ny(2026, 7, 12, 17, 0)), "open")

    def test_input_in_other_zone_is_converted(self):
        paris = ny(2026, 11, 13, 17, 0).astimezone(ZoneInfo("Europe/Paris"))
        self.assertEqual(sessions.market_state(paris), "closed_weekend")


class SessionTableTest(unittest.TestCase):
    def test_session_times_winter(self):
        t = sessions.session_table(utc(2026, 11, 13, 12, 0))
        london = row(t, "London")
        self.assertEqual(london["open_paris"], "09:00")
        self.assertEqual(london["close_paris"], "18:00")
        self.assertEqual(london["open_ny"], "03:00")
        ny_ = row(t, "New York")
        self.assertEqual(ny_["open_paris"], "14:00")
        self.assertEqual(ny_["close_paris"], "23:00")
        self.assertEqual(ny_["open_ny"], "08:00")
        self.assertEqual(ny_["close_ny"], "17:00")

    def test_session_times_us_dst_gap(self):
        t = sessions.session_table(utc(2026, 3, 16, 12, 0))
        ny_ = row(t, "New York")
        self.assertEqual(ny_["open_paris"], "13:00")
        self.assertEqual(ny_["close_paris"], "22:00")

    def test_entries_and_keys(self):
        t = sessions.session_table(utc(2026, 11, 13, 12, 0))
        self.assertEqual([r["name"] for r in t],
                         ["Sydney", "Tokyo", "London", "New York"])
        for r in t:
            self.assertEqual(set(r), {"name", "open_paris", "close_paris",
                                      "open_ny", "close_ny", "active"})

    def test_active_flag_london_midday_utc(self):
        t = sessions.session_table(utc(2026, 11, 13, 12, 0))
        self.assertTrue(row(t, "London")["active"])
        self.assertFalse(row(t, "New York")["active"])  # 12:00 UTC = 07:00 NY
        self.assertFalse(row(t, "Tokyo")["active"])  # 21:00 JST
        self.assertFalse(row(t, "Sydney")["active"])  # 23:00 Sydney

    def test_active_boundaries(self):
        # London winter == UTC: opens 08:00 UTC, closes 17:00 UTC
        self.assertFalse(row(sessions.session_table(utc(2026, 11, 13, 7, 59)), "London")["active"])
        self.assertTrue(row(sessions.session_table(utc(2026, 11, 13, 8, 0)), "London")["active"])
        self.assertTrue(row(sessions.session_table(utc(2026, 11, 13, 16, 59)), "London")["active"])
        self.assertFalse(row(sessions.session_table(utc(2026, 11, 13, 17, 0)), "London")["active"])

    def test_sydney_local_date_starts_previous_utc_day(self):
        # 22:00 UTC Nov 13 = 09:00 Nov 14 in Sydney (AEDT); window is
        # Nov 13 20:00 UTC to Nov 14 05:00 UTC.
        t = sessions.session_table(utc(2026, 11, 13, 22, 0))
        self.assertTrue(row(t, "Sydney")["active"])
        self.assertEqual(row(t, "Sydney")["open_paris"], "21:00")
        self.assertEqual(row(t, "Sydney")["close_paris"], "06:00")
        self.assertFalse(row(t, "London")["active"])

    def test_tokyo_has_no_dst(self):
        t = sessions.session_table(utc(2026, 7, 10, 0, 30))
        self.assertTrue(row(t, "Tokyo")["active"])  # 09:30 JST
        self.assertEqual(row(t, "Tokyo")["open_paris"], "02:00")  # Paris CEST

    def test_sydney_dst_vs_winter(self):
        # northern summer: Sydney on AEST (UTC+10); Paris on CEST (UTC+2)
        summer = row(sessions.session_table(utc(2026, 7, 10, 12, 0)), "Sydney")
        self.assertEqual(summer["open_paris"], "23:00")
        # northern winter: AEDT (UTC+11); Paris CET (UTC+1)
        winter = row(sessions.session_table(utc(2026, 11, 13, 12, 0)), "Sydney")
        self.assertEqual(winter["open_paris"], "21:00")


class OpenUtcTests(unittest.TestCase):
    def test_london_winter_and_summer(self):
        self.assertEqual(sessions.open_utc("London", utc(2026, 11, 16, 12)), utc(2026, 11, 16, 8))
        self.assertEqual(sessions.open_utc("London", utc(2026, 7, 15, 12)), utc(2026, 7, 15, 7))

    def test_new_york_winter(self):
        self.assertEqual(sessions.open_utc("New York", utc(2026, 11, 16, 12)), utc(2026, 11, 16, 13))

    def test_week_where_europe_and_us_differ(self):
        # Europe is back on winter time (25 Oct), the US still on summer time (until 1 Nov)
        now = utc(2026, 10, 28, 12)
        self.assertEqual(sessions.open_utc("New York", now), utc(2026, 10, 28, 12))
        self.assertEqual(sessions.open_utc("London", now), utc(2026, 10, 28, 8))

    def test_result_is_aware_utc(self):
        got = sessions.open_utc("Tokyo", utc(2026, 11, 16, 12))
        self.assertEqual(got.utcoffset().total_seconds(), 0)
        self.assertEqual(got, utc(2026, 11, 16, 0))

    def test_uses_local_date_of_the_session(self):
        # 2026-11-16 23:30 UTC is already 17 Nov in Tokyo
        self.assertEqual(sessions.open_utc("Tokyo", utc(2026, 11, 16, 23, 30)), utc(2026, 11, 17, 0))

    def test_unknown_session(self):
        with self.assertRaises(KeyError):
            sessions.open_utc("Mars", utc(2026, 11, 16, 12))


if __name__ == "__main__":
    unittest.main()
