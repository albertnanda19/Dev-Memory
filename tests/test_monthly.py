import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import monthly


class TestMonthlyAggregation(unittest.TestCase):
    def test_generate_monthly_report_aggregates(self):
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            f1 = tmp / "2026-02-01.json"
            f2 = tmp / "2026-02-02.json"
            f1.write_text(
                json.dumps(
                    {
                        "date": "2026-02-01",
                        "repos_touched": 1,
                        "committed": [
                            {
                                "repo_name": "payment",
                                "branch": "main",
                                "commits_count": 2,
                                "files_changed": 3,
                                "insertions": 100,
                                "deletions": 10,
                                "activity_type": "feature",
                            }
                        ],
                        "working_state": [],
                        "status": "success",
                    }
                ),
                encoding="utf-8",
            )
            f2.write_text(
                json.dumps(
                    {
                        "date": "2026-02-02",
                        "repos_touched": 1,
                        "committed": [
                            {
                                "repo_name": "payment",
                                "branch": "main",
                                "commits_count": 1,
                                "files_changed": 1,
                                "insertions": 10,
                                "deletions": 5,
                                "activity_type": "bugfix",
                            }
                        ],
                        "working_state": [],
                        "status": "success",
                    }
                ),
                encoding="utf-8",
            )

            with patch.object(monthly, "_iter_daily_json_files", return_value=[f1, f2]):
                data = monthly.generate_monthly_report("2026-02")

        self.assertEqual(data["month"], "2026-02")
        self.assertEqual(data["total_days_active"], 2)
        self.assertEqual(data["total_commits"], 3)
        self.assertEqual(data["total_files_changed"], 4)
        self.assertEqual(data["total_insertions"], 110)
        self.assertEqual(data["total_deletions"], 15)
        self.assertEqual(len(data["repositories"]), 1)
        repo = data["repositories"][0]
        self.assertEqual(repo["repo_name"], "payment")
        self.assertEqual(repo["activity_breakdown"].get("feature"), 1)
        self.assertEqual(repo["activity_breakdown"].get("bugfix"), 1)

    def test_generate_monthly_markdown_contains_sections(self):
        monthly_data = {
            "month": "2026-02",
            "total_days_active": 1,
            "total_commits": 2,
            "total_files_changed": 3,
            "total_insertions": 100,
            "total_deletions": 10,
            "repositories": [
                {
                    "repo_name": "payment",
                    "total_commits": 2,
                    "total_files_changed": 3,
                    "total_insertions": 100,
                    "total_deletions": 10,
                    "activity_breakdown": {"feature": 1},
                }
            ],
        }
        md = monthly.generate_monthly_markdown(monthly_data)
        self.assertIn("# Laporan Bulanan — 2026-02", md)
        self.assertIn("## Ikhtisar", md)
        self.assertIn("## Distribusi Jenis Aktivitas", md)
        self.assertIn("## Repository Paling Aktif", md)
        self.assertIn("## Insight Produktivitas (Rule-based)", md)
        self.assertIn("## Rincian Per Repository", md)
        self.assertIn("### payment", md)


if __name__ == "__main__":
    unittest.main()
