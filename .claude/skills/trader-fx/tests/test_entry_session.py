import _path  # noqa
import unittest
from datetime import datetime, timezone

import sessions


def utc(y, mo, d, h, mi=0):
    return datetime(y, mo, d, h, mi, tzinfo=timezone.utc)


class TestEntrySession(unittest.TestCase):
    """Session of an entry: among the sessions active at that instant, the one that opened most
    recently. Winter 2026 in UTC: Sydney 20:00-05:00, Tokyo 00:00-09:00, London 08:00-17:00,
    New York 13:00-22:00."""

    def test_winter_cases_computed_by_hand(self):
        self.assertEqual(sessions.entry_session(utc(2026, 11, 13, 12)), "London")      # NY not open yet
        self.assertEqual(sessions.entry_session(utc(2026, 11, 13, 14)), "New York")    # NY opened last
        self.assertEqual(sessions.entry_session(utc(2026, 11, 13, 22, 30)), "Sydney")  # NY closed 22:00
        self.assertEqual(sessions.entry_session(utc(2026, 11, 13, 6)), "Tokyo")        # Sydney closed 05:00
        self.assertEqual(sessions.entry_session(utc(2026, 11, 18, 1)), "Tokyo")        # Tokyo 00:00 > Sydney 20:00
        self.assertEqual(sessions.entry_session(utc(2026, 11, 18, 21)), "Sydney")      # Sydney 20:00 > NY 13:00

    def test_summer_case(self):
        # London BST opens 07:00 UTC, Tokyo opened 00:00 UTC
        self.assertEqual(sessions.entry_session(utc(2026, 7, 15, 7, 30)), "London")

    def test_session_boundaries(self):
        self.assertEqual(sessions.entry_session(utc(2026, 11, 13, 13, 0)), "New York")   # opens exactly
        self.assertEqual(sessions.entry_session(utc(2026, 11, 13, 22, 0)), "Sydney")     # NY closes exactly

    def test_outside_every_session(self):
        only_london = {"London": ("Europe/London", 8, 17)}
        self.assertEqual(sessions.entry_session(utc(2026, 11, 13, 20), only_london), "hors session")
        self.assertEqual(sessions.entry_session(utc(2026, 11, 13, 9), only_london), "London")

    def test_a_naive_time_is_refused(self):
        with self.assertRaises(ValueError):
            sessions.entry_session(datetime(2026, 11, 13, 12))


if __name__ == "__main__":
    unittest.main()
