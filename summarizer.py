
from __future__ import annotations

import json
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

from models import DailyReport


def _load_ai_client():
    mod_path = Path(__file__).resolve().parent / "llm-client.py"
    spec = spec_from_file_location("dev_memory_llm_client", mod_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load llm-client.py")
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def generate_daily_narrative(report: DailyReport) -> str:
    report_data = report.model_dump() if hasattr(report, "model_dump") else report.__dict__
    prompt = "\n".join(
        [
            "You are a senior software engineer writing a professional daily standup summary.",
            "",
            "Here is structured data:",
            json.dumps(report_data, indent=2),
            "",
            "Write:",
            "- 1 paragraph executive summary",
            "- Bullet list of major contributions",
            "- Clear statement of carry-over work",
            "- Professional tone",
            "- No emojis",
            "- No exaggeration",
            "- No hallucination",
            "- Only use given data",
        ]
    )

    client = _load_ai_client()
    return client.generate_ai_summary(prompt)


def generate_markdown(report: DailyReport, include_ai: bool = False) -> str:
    parts: list[str] = []

    date_str = getattr(report, "date", "")
    parts.append(f"# Daily Report — {date_str}")
    parts.append("")

    if getattr(report, "status", None) == "no_activity":
        parts.append("No development activity detected.")
        parts.append("")
        return "\n".join(parts)

    committed = getattr(report, "committed", None) or []
    total_commits = sum(getattr(x, "commits_count", 0) for x in committed)
    total_files_changed = sum(getattr(x, "files_changed", 0) for x in committed)

    parts.append("## Summary")
    parts.append(f"- Repositories touched: {getattr(report, 'repos_touched', 0)}")
    parts.append(f"- Total commits: {total_commits}")
    parts.append(f"- Total files changed: {total_files_changed}")
    parts.append("")
    parts.append("---")
    parts.append("")

    parts.append("## Repository Breakdown")
    parts.append("")

    for repo in committed:
        parts.append(f"### {getattr(repo, 'repo_name', '')}")
        parts.append(f"Branch: {getattr(repo, 'branch', '')}  ")
        parts.append(f"Commits: {getattr(repo, 'commits_count', 0)}  ")
        parts.append(f"Files Changed: {getattr(repo, 'files_changed', 0)}  ")
        parts.append(f"Insertions: {getattr(repo, 'insertions', 0)}  ")
        parts.append(f"Deletions: {getattr(repo, 'deletions', 0)}  ")
        parts.append(f"Activity Type: {getattr(repo, 'activity_type', 'improvement')}  ")
        parts.append("")

    parts.append("---")
    parts.append("")

    working_state = getattr(report, "working_state", None) or []
    if working_state:
        parts.append("## Uncommitted Work (Carry Over)")
        parts.append("")
        for ws in working_state:
            parts.append(f"### {getattr(ws, 'repo_name', '')}")
            parts.append(f"Branch: {getattr(ws, 'branch', '')}  ")
            parts.append("Modified Files:")
            for path in (getattr(ws, "modified_files", None) or []):
                parts.append(f"- {path}")
            parts.append("")

        parts.append("---")
        parts.append("")

    parts.append("## Standup Template")
    parts.append("")
    parts.append("Yesterday:")
    for repo in committed:
        parts.append(
            f"- Worked on {getattr(repo, 'repo_name', '')} ({getattr(repo, 'activity_type', 'improvement')})"
        )
    if not committed:
        parts.append("- No committed work")
    parts.append("")

    parts.append("Today:")
    if working_state:
        seen: set[str] = set()
        for ws in working_state:
            repo_name = getattr(ws, "repo_name", "")
            if repo_name in seen:
                continue
            seen.add(repo_name)
            parts.append(f"- Continue uncommitted changes in {repo_name}")
    else:
        parts.append("- Continue feature development")
    parts.append("")

    parts.append("Blockers:")
    parts.append("- None")
    parts.append("")

    if include_ai:
        try:
            narrative = generate_daily_narrative(report)
        except Exception as e:
            print(f"Warning: AI narrative generation failed: {e}")
            narrative = ""

        if narrative.strip():
            parts.append("---")
            parts.append("")
            parts.append("## AI Narrative Summary")
            parts.append("")
            parts.append(narrative.strip())
            parts.append("")

    return "\n".join(parts)
