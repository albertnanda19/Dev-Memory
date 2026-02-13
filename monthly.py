from __future__ import annotations

import json
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from typing import Any


def _iter_daily_json_files(*, month: str) -> list[Path]:
    base_dir = Path(__file__).resolve().parent
    daily_dir = base_dir / "data" / "daily"
    if not daily_dir.exists():
        return []

    files = [
        p
        for p in daily_dir.iterdir()
        if p.is_file() and p.suffix == ".json" and p.stem.startswith(month)
    ]
    files.sort(key=lambda p: p.name)
    return files


def generate_monthly_report(month: str) -> dict[str, Any]:
    daily_files = _iter_daily_json_files(month=month)
    if not daily_files:
        raise FileNotFoundError(f"No daily reports found for {month}")

    totals = {
        "month": month,
        "total_days_active": 0,
        "total_commits": 0,
        "total_files_changed": 0,
        "total_insertions": 0,
        "total_deletions": 0,
    }

    repos: dict[str, dict[str, Any]] = {}

    for path in daily_files:
        data = json.loads(path.read_text(encoding="utf-8") or "{}")
        if data.get("status") == "no_activity":
            continue

        totals["total_days_active"] += 1

        committed = data.get("committed") or []
        for item in committed:
            repo_name = item.get("repo_name", "")
            if not repo_name:
                continue

            repo = repos.get(repo_name)
            if repo is None:
                repo = {
                    "repo_name": repo_name,
                    "total_commits": 0,
                    "total_files_changed": 0,
                    "total_insertions": 0,
                    "total_deletions": 0,
                    "activity_breakdown": {},
                }
                repos[repo_name] = repo

            commits_count = int(item.get("commits_count", 0) or 0)
            files_changed = int(item.get("files_changed", 0) or 0)
            insertions = int(item.get("insertions", 0) or 0)
            deletions = int(item.get("deletions", 0) or 0)

            totals["total_commits"] += commits_count
            totals["total_files_changed"] += files_changed
            totals["total_insertions"] += insertions
            totals["total_deletions"] += deletions

            repo["total_commits"] += commits_count
            repo["total_files_changed"] += files_changed
            repo["total_insertions"] += insertions
            repo["total_deletions"] += deletions

            activity_type = item.get("activity_type") or "improvement"
            breakdown = repo["activity_breakdown"]
            breakdown[activity_type] = int(breakdown.get(activity_type, 0)) + 1

    monthly_data: dict[str, Any] = dict(totals)
    repositories = list(repos.values())
    repositories.sort(key=lambda r: r.get("repo_name", ""))

    # remove zero-count entries (and keep output stable)
    for repo in repositories:
        breakdown = repo.get("activity_breakdown") or {}
        repo["activity_breakdown"] = {
            k: breakdown[k] for k in sorted(breakdown.keys()) if int(breakdown[k]) > 0
        }

    monthly_data["repositories"] = repositories
    return monthly_data


def _load_ai_client():
    mod_path = Path(__file__).resolve().parent / "llm-client.py"
    spec = spec_from_file_location("dev_memory_llm_client", mod_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load llm-client.py")
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def generate_monthly_narrative(monthly_data: dict[str, Any]) -> str:
    prompt = "\n".join(
        [
            "You are preparing a professional monthly engineering report.",
            "",
            "Based only on the structured data below:",
            json.dumps(monthly_data, indent=2),
            "",
            "Write:",
            "1. Executive overview paragraph",
            "2. Key impact areas",
            "3. Engineering patterns observed (features vs bugfix vs refactor ratio)",
            "4. Areas for next month focus",
            "",
            "Do NOT invent metrics.",
            "Use only given data.",
            "Professional tone.",
        ]
    )

    client = _load_ai_client()
    return client.generate_ai_summary(prompt)


def generate_monthly_markdown(monthly_data: dict[str, Any], include_ai: bool = False) -> str:
    parts: list[str] = []

    month = str(monthly_data.get("month", ""))
    parts.append(f"# Monthly Report — {month}")
    parts.append("")

    parts.append("## Overview")
    parts.append(f"- Active Days: {int(monthly_data.get('total_days_active', 0) or 0)}")
    parts.append(f"- Total Commits: {int(monthly_data.get('total_commits', 0) or 0)}")
    parts.append(
        f"- Total Files Changed: {int(monthly_data.get('total_files_changed', 0) or 0)}"
    )
    parts.append(
        f"- Total Insertions: {int(monthly_data.get('total_insertions', 0) or 0)}"
    )
    parts.append(
        f"- Total Deletions: {int(monthly_data.get('total_deletions', 0) or 0)}"
    )
    parts.append("")
    parts.append("---")
    parts.append("")

    parts.append("## Repository Breakdown")
    parts.append("")

    repositories = monthly_data.get("repositories") or []
    for repo in repositories:
        repo_name = repo.get("repo_name", "")
        parts.append(f"### {repo_name}")
        parts.append(f"Total Commits: {int(repo.get('total_commits', 0) or 0)}  ")
        parts.append(
            f"Files Changed: {int(repo.get('total_files_changed', 0) or 0)}  "
        )
        parts.append(f"Insertions: {int(repo.get('total_insertions', 0) or 0)}  ")
        parts.append(f"Deletions: {int(repo.get('total_deletions', 0) or 0)}  ")
        parts.append("")

        parts.append("Activity Distribution:")
        breakdown = repo.get("activity_breakdown") or {}
        for key in sorted(breakdown.keys()):
            parts.append(f"- {key}: {int(breakdown.get(key, 0) or 0)}")
        parts.append("")

    if include_ai:
        try:
            narrative = generate_monthly_narrative(monthly_data)
        except Exception as e:
            print(f"Warning: AI narrative generation failed: {e}")
            narrative = ""

        if narrative.strip():
            parts.append("---")
            parts.append("")
            parts.append("## AI Executive Narrative")
            parts.append("")
            parts.append(narrative.strip())
            parts.append("")

    return "\n".join(parts)
