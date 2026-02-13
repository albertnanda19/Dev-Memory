import unittest
from unittest.mock import patch

import scheduler


class TestScheduler(unittest.TestCase):
    def test_install_idempotent(self):
        existing = "0 8 * * 1-5 /x /y >> /z 2>&1 # dev-memory:run_daily\n"
        with patch("builtins.print"), patch(
            "scheduler._read_crontab", return_value=existing
        ), patch("scheduler._write_crontab") as write_mock:
            scheduler.install_cron_job()
            write_mock.assert_not_called()

    def test_remove_when_missing(self):
        with patch("builtins.print"), patch(
            "scheduler._read_crontab", return_value=""
        ), patch("scheduler._write_crontab") as write_mock:
            scheduler.remove_cron_job()
            write_mock.assert_not_called()


if __name__ == "__main__":
    unittest.main()
