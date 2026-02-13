import unittest
from unittest.mock import patch

from models import DailyReport, RepoCommittedSummary, RepoWorkingState
from summarizer import generate_markdown


class TestDailyMarkdown(unittest.TestCase):
    def test_no_activity_markdown(self):
        report = DailyReport(
            date="2026-02-12",
            repos_touched=0,
            committed=[],
            working_state=[],
            status="no_activity",
        )
        md = generate_markdown(report)
        self.assertIn("# Daily Report — 2026-02-12", md)
        self.assertIn("No development activity detected.", md)

    def test_ai_failure_does_not_crash(self):
        report = DailyReport(
            date="2026-02-13",
            repos_touched=1,
            committed=[
                RepoCommittedSummary(
                    repo_name="repo",
                    branch="main",
                    commits_count=1,
                    files_changed=1,
                    insertions=10,
                    deletions=0,
                    activity_type="bugfix",
                )
            ],
            working_state=[
                RepoWorkingState(
                    repo_name="repo",
                    branch="main",
                    modified_files=["a.py"],
                    untracked_files=[],
                    insertions=0,
                    deletions=0,
                )
            ],
            status="success",
        )

        with patch("summarizer.generate_daily_narrative", side_effect=RuntimeError("boom")):
            md = generate_markdown(report, include_ai=True)

        self.assertIn("# Daily Report — 2026-02-13", md)
        self.assertNotIn("## AI Narrative Summary", md)


if __name__ == "__main__":
    unittest.main()
