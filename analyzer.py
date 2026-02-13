
from __future__ import annotations

from models import DailyReport


_ALLOWED_ACTIVITY_TYPES = {
    "feature",
    "bugfix",
    "refactor",
    "improvement",
    "no_activity",
}


def _classify_summary(
    *,
    commits_count: int,
    files_changed: int,
    insertions: int,
    deletions: int,
) -> str:
    if commits_count == 0:
        return "no_activity"
    if insertions > 200:
        return "feature"
    if files_changed <= 2 and insertions < 50:
        return "bugfix"
    if deletions > insertions:
        return "refactor"
    if 50 <= insertions <= 200:
        return "improvement"
    return "improvement"


def classify_activity(report: DailyReport) -> DailyReport:
    if getattr(report, "status", None) == "no_activity":
        return report

    committed = getattr(report, "committed", None) or []
    for summary in committed:
        activity_type = _classify_summary(
            commits_count=getattr(summary, "commits_count", 0),
            files_changed=getattr(summary, "files_changed", 0),
            insertions=getattr(summary, "insertions", 0),
            deletions=getattr(summary, "deletions", 0),
        )
        if activity_type not in _ALLOWED_ACTIVITY_TYPES:
            activity_type = "improvement"
        setattr(summary, "activity_type", activity_type)

    return report
