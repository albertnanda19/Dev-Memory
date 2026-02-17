
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
from pathlib import Path

from analyzer import classify_activity
from collector import collect_daily_activity
from config import get_repo_paths
from monthly import generate_monthly_markdown, generate_monthly_report
from reporter import save_daily_markdown, save_monthly_json, save_monthly_markdown
from scheduler import (
    install_cron_job,
    install_startup_hook,
    remove_cron_job,
    remove_startup_hook,
)
from summarizer import generate_markdown


def _yesterday_date_str() -> str:
    return (_dt.date.today() - _dt.timedelta(days=1)).strftime("%Y-%m-%d")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="dev-memory")
    parser.add_argument(
        "--bot",
        action="store_true",
        help="Start Discord bot runtime (slash commands)",
    )
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
        "--daily-ai-discord",
        action="store_true",
        help="Generate daily report with AI narrative and send it to Discord",
    )
    parser.add_argument(
        "--send-discord",
        metavar="YYYY-MM-DD",
        default=None,
        help="Send an existing daily Markdown report to Discord (does not generate a new report)",
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
    parser.add_argument(
        "--install-startup",
        action="store_true",
        help="Install a Linux autostart hook that runs run_on_startup.py on login",
    )
    parser.add_argument(
        "--remove-startup",
        action="store_true",
        help="Remove the dev-memory Linux autostart hook if installed",
    )
    return parser.parse_args()


def _run_daily(*, include_ai: bool) -> str:
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
    return date_str


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


def _send_discord(*, date_str: str) -> None:
    from discord_delivery.send_report import send_daily_standup

    root = Path(__file__).resolve().parent
    md_path = root / "data" / "daily" / f"{date_str}.md"
    json_path = root / "data" / "daily" / f"{date_str}.json"

    try:
        res = send_daily_standup(
            date_str=date_str,
            markdown_path=md_path,
            daily_json_path=json_path,
        )
    except Exception as e:
        print(f"Discord send failed: {e}")
        return

    if res.ok:
        print("Discord send success")
    else:
        print(
            f"Discord send failed (http={res.status_code} retry={res.retry_count} error={res.error})"
        )


def main() -> None:
    args = _parse_args()
    if args.bot:
        from bot import run_bot

        run_bot()
        return
    if args.install_cron:
        install_cron_job()
        return
    if args.remove_cron:
        remove_cron_job()
        return
    if args.install_startup:
        install_startup_hook()
        return
    if args.remove_startup:
        remove_startup_hook()
        return
    if args.daily_ai_discord:
        date_str = _run_daily(include_ai=True)
        _send_discord(date_str=date_str)
        return
    if args.send_discord:
        _send_discord(date_str=str(args.send_discord))
        return
    if args.monthly:
        _run_monthly(month=args.monthly, include_ai=bool(args.ai))
        return

    _run_daily(include_ai=bool(args.ai))


if __name__ == "__main__":
    main()

