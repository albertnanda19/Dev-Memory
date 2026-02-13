import unittest
from unittest.mock import patch

import collector

import datetime as _real_dt


class TestCollectorDateRange(unittest.TestCase):
    def test_monday_uses_fri_to_sun(self):
        real_date = _real_dt.date

        class _FakeDate:
            @staticmethod
            def today():
                # Monday
                return real_date(2026, 3, 2)

        with patch("collector._dt.date", _FakeDate):
            date_str, since, until = collector._activity_range()

        self.assertEqual(date_str, "2026-03-01")
        self.assertEqual(since, "2026-02-27 06:00")
        self.assertEqual(until, "2026-03-02 05:59")

    def test_non_monday_uses_yesterday_only(self):
        real_date = _real_dt.date

        class _FakeDate:
            @staticmethod
            def today():
                # Tuesday
                return real_date(2026, 3, 3)

        with patch("collector._dt.date", _FakeDate):
            date_str, since, until = collector._activity_range()

        self.assertEqual(date_str, "2026-03-02")
        self.assertEqual(since, "2026-03-02 06:00")
        self.assertEqual(until, "2026-03-03 05:59")


if __name__ == "__main__":
    unittest.main()
