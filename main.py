
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os

from analyzer import classify_activity
from collector import collect_daily_activity
from config import get_repo_paths
from monthly import generate_monthly_markdown, generate_monthly_report
from reporter import save_daily_markdown, save_monthly_json, save_monthly_markdown
from scheduler import install_cron_job, remove_cron_job
from summarizer import generate_markdown


def _yesterday_date_str() -> str:
    return (_dt.date.today() - _dt.timedelta(days=1)).strftime("%Y-%m-%d")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="dev-memory")
    parser.add_argument(
        "--monthly",
        metavar="YYYY-MM",
        default=None,
        help="Generate a monthly aggregated report from daily JSON files",
    )
    parser.add_argument(
        "--ai",
        action="store_true",
        help="Append optional AI narrative sections to generated Markdown (presentation-only)",
    )
    parser.add_argument(
        "--install-cron",
        action="store_true",
        help="Install a weekday 08:00 cron job that runs run_daily.py",
    )
    parser.add_argument(
        "--remove-cron",
        action="store_true",
        help="Remove the dev-memory cron job if installed",
    )
    return parser.parse_args()


def _run_daily(*, include_ai: bool) -> None:
    repo_paths = get_repo_paths()
    report = collect_daily_activity(repo_paths)
    report = classify_activity(report)

    date_str = report.date or _yesterday_date_str()
    daily_dir = os.path.join(os.path.dirname(__file__), "data", "daily")
    os.makedirs(daily_dir, exist_ok=True)
    out_path = os.path.join(daily_dir, f"{date_str}.json")

    tmp_path = f"{out_path}.tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(report.model_dump(), f, indent=2)
        f.write("\n")
    os.replace(tmp_path, out_path)

    markdown = generate_markdown(report, include_ai=include_ai)
    save_daily_markdown(report, markdown)

    print(f"Daily report generated for {date_str}")


def _run_monthly(*, month: str, include_ai: bool) -> None:
    try:
        monthly_data = generate_monthly_report(month)
    except FileNotFoundError:
        print(f"No daily reports found for {month}")
        return

    save_monthly_json(month, monthly_data)
    markdown = generate_monthly_markdown(monthly_data, include_ai=include_ai)
    save_monthly_markdown(month, markdown)
    print(f"Monthly report generated for {month}")


def main() -> None:
    args = _parse_args()
    if args.install_cron:
        install_cron_job()
        return
    if args.remove_cron:
        remove_cron_job()
        return
    if args.monthly:
        _run_monthly(month=args.monthly, include_ai=bool(args.ai))
        return

    _run_daily(include_ai=bool(args.ai))


if __name__ == "__main__":
    main()

