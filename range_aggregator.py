from __future__ import annotations

import datetime as _dt
import json
from pathlib import Path
from typing import Any

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
    }
