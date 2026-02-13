import unittest

from analyzer import classify_activity
from models import DailyReport, RepoCommittedSummary, RepoWorkingState


class TestAnalyzerClassification(unittest.TestCase):
    def test_no_activity_status_skips(self):
        report = DailyReport(
            date="2026-02-12",
            repos_touched=0,
            committed=[],
            working_state=[],
            status="no_activity",
        )
        out = classify_activity(report)
        self.assertEqual(out.committed, [])

    def test_rules_in_order(self):
        committed = [
            RepoCommittedSummary(
                repo_name="r0",
                branch="main",
                commits_count=0,
                files_changed=0,
                insertions=0,
                deletions=0,
            ),
            RepoCommittedSummary(
                repo_name="r1",
                branch="main",
                commits_count=1,
                files_changed=10,
                insertions=201,
                deletions=0,
            ),
            RepoCommittedSummary(
                repo_name="r2",
                branch="main",
                commits_count=1,
                files_changed=2,
                insertions=49,
                deletions=0,
            ),
            RepoCommittedSummary(
                repo_name="r3",
                branch="main",
                commits_count=1,
                files_changed=10,
                insertions=10,
                deletions=20,
            ),
            RepoCommittedSummary(
                repo_name="r4",
                branch="main",
                commits_count=1,
                files_changed=10,
                insertions=50,
                deletions=0,
            ),
        ]
        report = DailyReport(
            date="2026-02-13",
            repos_touched=5,
            committed=committed,
            working_state=[
                RepoWorkingState(
                    repo_name="r4",
                    branch="main",
                    modified_files=[],
                    untracked_files=[],
                    insertions=0,
                    deletions=0,
                )
            ],
            status="success",
        )
        out = classify_activity(report)
        got = {c.repo_name: c.activity_type for c in out.committed}
        self.assertEqual(got["r0"], "no_activity")
        self.assertEqual(got["r1"], "feature")
        self.assertEqual(got["r2"], "bugfix")
        self.assertEqual(got["r3"], "refactor")
        self.assertEqual(got["r4"], "improvement")


if __name__ == "__main__":
    unittest.main()
