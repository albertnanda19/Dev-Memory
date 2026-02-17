from __future__ import annotations

import datetime as _dt
import json
from pathlib import Path
from typing import Any

from commit_collector import RepoRawCommits, collect_commits_for_repos
from config import get_repo_paths
from logger import get_logger


_LOG = get_logger()


def _parse_date(date_str: str) -> _dt.date:
    return _dt.datetime.strptime(date_str, "%Y-%m-%d").date()


def _daily_dir() -> Path:
    return Path(__file__).resolve().parent / "data" / "daily"


def _safe_int(value: Any) -> int:
    try:
        return int(value or 0)
    except Exception:
        return 0


def _iter_dates(start: _dt.date, end: _dt.date):
    day = start
    one = _dt.timedelta(days=1)
    while day <= end:
        yield day
        day += one


def _read_json_file(path: Path) -> dict[str, Any] | None:
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        _LOG.info("range_aggregator missing_file path=%s", str(path))
        return None
    except Exception as e:
        _LOG.exception("range_aggregator read_failed path=%s err=%s", str(path), str(e))
        return None

    try:
        data = json.loads(raw or "{}")
    except json.JSONDecodeError as e:
        _LOG.warning("range_aggregator corrupted_json path=%s err=%s", str(path), str(e))
        return None
    except Exception as e:
        _LOG.warning("range_aggregator json_parse_failed path=%s err=%s", str(path), str(e))
        return None

    if not isinstance(data, dict):
        _LOG.warning("range_aggregator invalid_json_root path=%s", str(path))
        return None

    return data


def _repo_raw_to_dict(repo: RepoRawCommits) -> dict[str, Any]:
    detailed_commits: list[dict[str, Any]] = []
    for c in repo.commits:
        files = [{"path": f.path} for f in c.files]
        detailed_commits.append(
            {
                "hash": c.commit_hash,
                "date": c.commit_date,
                "message": c.message,
                "files": files,
            }
        )
    return {
        "name": repo.repository,
        "repo_path": repo.repo_path,
        "commit_count_expected": int(repo.commit_count_expected),
        "commit_count": len(detailed_commits),
        "detailed_commits": detailed_commits,
    }


def get_repo_achievements_in_range(start_date: str, end_date: str) -> dict[str, Any]:
    repo_paths = get_repo_paths()
    repos = collect_commits_for_repos(repo_paths=repo_paths, start_date=start_date, end_date=end_date)

    repositories: list[dict[str, Any]] = []
    total_expected = 0
    total_parsed = 0

    for r in repos:
        repo_dict = _repo_raw_to_dict(r)
        repositories.append(repo_dict)
        total_expected += int(repo_dict.get("commit_count_expected") or 0)
        total_parsed += int(repo_dict.get("commit_count") or 0)

    if total_expected != total_parsed:
        _LOG.error(
            "range_aggregator integrity_mismatch expected=%s parsed=%s start=%s end=%s",
            total_expected,
            total_parsed,
            start_date,
            end_date,
        )
        raise RuntimeError(
            f"integrity mismatch: expected={total_expected} parsed={total_parsed} ({start_date}..{end_date})"
        )

    repositories.sort(key=lambda x: str(x.get("name") or ""))
    return {
        "start_date": start_date,
        "end_date": end_date,
        "repositories": repositories,
        "total_commits_expected": total_expected,
        "total_commits": total_parsed,
    }


def get_reports_in_range(start_date: str, end_date: str) -> list[dict[str, Any]]:
    start = _parse_date(start_date)
    end = _parse_date(end_date)

    base = _daily_dir()
    out: list[dict[str, Any]] = []

    for day in _iter_dates(start, end):
        path = base / f"{day.strftime('%Y-%m-%d')}.json"
        data = _read_json_file(path)
        if not data:
            continue
        out.append(data)

    return out


def _iter_files_from_report(report: dict[str, Any]):
    committed = report.get("committed")
    if not isinstance(committed, list):
        return

    for repo in committed:
        if not isinstance(repo, dict):
            continue
        details = repo.get("commit_details")
        if not isinstance(details, list):
            continue
        for item in details:
            if not isinstance(item, dict):
                continue
            files = item.get("files")
            if not isinstance(files, list):
                continue
            for fp in files:
                if isinstance(fp, str) and fp.strip():
                    yield fp.strip()


def _iter_commit_items(report: dict[str, Any]):
    committed = report.get("committed")
    if not isinstance(committed, list):
        return
    for repo in committed:
        if not isinstance(repo, dict):
            continue
        repo_name = repo.get("repo_name")
        repo_name = repo_name.strip() if isinstance(repo_name, str) else ""
        details = repo.get("commit_details")
        if not isinstance(details, list):
            continue
        for item in details:
            if not isinstance(item, dict):
                continue
            msg = item.get("message")
            msg = msg.strip() if isinstance(msg, str) else ""
            files = item.get("files")
            if not isinstance(files, list):
                files = []
            file_list = [f.strip() for f in files if isinstance(f, str) and f.strip()]
            yield repo_name, msg, file_list


def _dir_key(file_path: str) -> str:
    p = file_path.strip().lstrip("/")
    if not p:
        return ""
    head = p.split("/", 1)[0].strip()
    if not head:
        return ""
    return head + "/"


def _ext_key(file_path: str) -> str:
    name = file_path.strip().rsplit("/", 1)[-1]
    if not name or name in {".", ".."}:
        return ""
    suffix = Path(name).suffix
    return suffix or ""


def _classify_intent(message: str) -> str:
    m = message.lower().strip()
    if not m:
        return "chore"

    if any(k in m for k in ["validate", "validation", "sanitize", "guard", "constraint"]):
        return "validation"
    if any(k in m for k in ["optimize", "perf", "performance", "speed", "latency", "cache"]):
        return "performance"
    if any(k in m for k in ["infra", "ci", "cd", "pipeline", "docker", "k8s", "deploy"]):
        return "infra"
    if any(k in m for k in ["refactor", "cleanup", "simplify", "restructure"]):
        return "refactor"
    if any(k in m for k in ["test", "tests", "spec"]):
        return "test"
    if any(k in m for k in ["fix", "bug", "issue", "hotfix", "patch"]):
        return "fix"
    if any(k in m for k in ["add", "implement", "create", "introduce", "integrate", "build"]):
        return "feature"

    conventional = ["feat", "fix", "refactor", "test", "chore", "perf", "ci"]
    for p in conventional:
        if m.startswith(p + ":"):
            return "feature" if p == "feat" else ("performance" if p == "perf" else ("infra" if p == "ci" else p))

    return "chore"


def _group_files_by_directory(files: list[str]) -> dict[str, list[str]]:
    grouped: dict[str, list[str]] = {}
    for fp in files:
        d = _dir_key(fp) or "(root)"
        arr = grouped.get(d)
        if arr is None:
            arr = []
            grouped[d] = arr
        if fp not in arr:
            arr.append(fp)
    for k in list(grouped.keys()):
        grouped[k].sort()
    return dict(sorted(grouped.items(), key=lambda x: x[0]))


def _action_verbs(intent: str) -> list[str]:
    mapping = {
        "feature": ["implemented", "added", "created", "integrated"],
        "fix": ["fixed", "resolved", "stabilized"],
        "refactor": ["refactored", "simplified", "restructured"],
        "test": ["added tests", "validated"],
        "chore": ["updated", "adjusted"],
        "infra": ["configured", "automated"],
        "validation": ["introduced validation", "added safeguards"],
        "performance": ["optimized", "improved performance"],
    }
    return mapping.get(intent, ["updated"])


def _rank(counter: dict[str, int], *, limit: int = 10) -> list[str]:
    items = [(k, int(v or 0)) for k, v in counter.items() if k and int(v or 0) > 0]
    items.sort(key=lambda x: (-x[1], x[0]))
    return [k for k, _ in items[:limit]]


def aggregate_reports(report_list: list[dict[str, Any]]) -> dict[str, Any]:
    dates: list[str] = []

    total_commits = 0
    total_files_changed = 0
    total_insertions = 0
    total_deletions = 0

    dir_counts: dict[str, int] = {}
    ext_counts: dict[str, int] = {}

    detailed_by_key: dict[tuple[str, str], dict[str, Any]] = {}
    all_files: list[str] = []

    for report in report_list:
        if not isinstance(report, dict):
            continue

        status = report.get("status")
        if status == "no_activity":
            continue

        date_str = report.get("date")
        if isinstance(date_str, str) and date_str.strip():
            dates.append(date_str.strip())

        committed = report.get("committed")
        if isinstance(committed, list):
            for repo in committed:
                if not isinstance(repo, dict):
                    continue
                total_commits += _safe_int(repo.get("commits_count"))
                total_files_changed += _safe_int(repo.get("files_changed"))
                total_insertions += _safe_int(repo.get("insertions"))
                total_deletions += _safe_int(repo.get("deletions"))

        for repo_name, msg, files in _iter_commit_items(report):
            if not msg and not files:
                continue

            intent = _classify_intent(msg)
            key = (intent, msg)
            existing = detailed_by_key.get(key)
            if existing is None:
                existing = {
                    "type": intent,
                    "description": msg,
                    "repos": sorted([repo_name]) if repo_name else [],
                    "files": sorted(set(files)),
                    "action_verbs": _action_verbs(intent),
                }
                detailed_by_key[key] = existing
            else:
                if repo_name and repo_name not in (existing.get("repos") or []):
                    repos = list(existing.get("repos") or [])
                    repos.append(repo_name)
                    repos.sort()
                    existing["repos"] = repos
                prev_files = set(existing.get("files") or [])
                for f in files:
                    prev_files.add(f)
                existing["files"] = sorted(prev_files)

            for f in files:
                all_files.append(f)

        for fp in _iter_files_from_report(report):
            d = _dir_key(fp)
            if d:
                dir_counts[d] = int(dir_counts.get(d, 0)) + 1
            e = _ext_key(fp)
            if e:
                ext_counts[e] = int(ext_counts.get(e, 0)) + 1

    dates_sorted = sorted(set(dates))
    start = dates_sorted[0] if dates_sorted else ""
    end = dates_sorted[-1] if dates_sorted else ""

    detailed_changes = list(detailed_by_key.values())
    detailed_changes.sort(key=lambda x: (str(x.get("type", "")), str(x.get("description", ""))))
    files_by_directory = _group_files_by_directory(all_files)

    return {
        "start_date": start,
        "end_date": end,
        "total_days": len(dates_sorted),
        "total_commits": total_commits,
        "total_files_changed": total_files_changed,
        "total_insertions": total_insertions,
        "total_deletions": total_deletions,
        "top_directories": _rank(dir_counts),
        "top_file_types": _rank(ext_counts),
        "files_by_directory": files_by_directory,
        "detailed_changes": detailed_changes,
    }
