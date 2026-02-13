import datetime as _dt
import unittest
from unittest.mock import patch

import run_daily


class TestRunDaily(unittest.TestCase):
    def test_weekend_exits_silently(self):
        # Saturday
        with patch("run_daily._today", return_value=_dt.date(2026, 2, 14)), patch(
            "run_daily.subprocess.run"
        ) as run_mock:
            run_daily.main()
            run_mock.assert_not_called()

    def test_first_weekday_triggers_monthly(self):
        # 2026-03-02 is Monday, also first weekday
        ok = type(
            "_CP",
            (),
            {
                "returncode": 0,
                "stdout": "",
                "stderr": "",
            },
        )()

        with patch("run_daily._today", return_value=_dt.date(2026, 3, 2)), patch(
            "run_daily.subprocess.run", return_value=ok
        ) as run_mock:
            run_daily.main()
            # daily + monthly
            self.assertEqual(run_mock.call_count, 2)


if __name__ == "__main__":
    unittest.main()
