from __future__ import annotations

import datetime as _dt
import subprocess
import sys
import time
from pathlib import Path

import collector
from logger import get_logger


_LOG = get_logger()


def _project_root() -> Path:
    return Path(__file__).resolve().parent


def _is_weekday(day: _dt.date) -> bool:
    return day.weekday() < 5


def _today() -> _dt.date:
    return _dt.date.today()


def _is_first_weekday_of_month(day: _dt.date) -> bool:
    first = day.replace(day=1)
    d = first
    while d.weekday() >= 5:
        d = d + _dt.timedelta(days=1)
    return day == d


def _previous_month(day: _dt.date) -> str:
    first_of_month = day.replace(day=1)
    prev_last_day = first_of_month - _dt.timedelta(days=1)
    return prev_last_day.strftime("%Y-%m")


def _run_main(args: list[str]) -> None:
    cmd = [sys.executable, str(_project_root() / "main.py"), *args]
    cp = subprocess.run(
        cmd,
        cwd=str(_project_root()),
        capture_output=True,
        text=True,
        check=False,
    )
    if cp.returncode != 0:
        raise RuntimeError(
            f"main.py gagal (rc={cp.returncode}): {cp.stderr.strip() or cp.stdout.strip()}"
        )


def main() -> None:
    start_ts = time.perf_counter()
    _LOG.info("Execution started")
    _LOG.info("Python version: %s", sys.version.replace("\n", " "))
    _LOG.info("Working directory: %s", str(_project_root()))

    today = _today()
    if not _is_weekday(today):
        _LOG.info("Weekend detected, exit")
        return

    try:
        date_str, since, until = collector._activity_range()
        _LOG.info("Time window: %s -> %s (label=%s)", since, until, date_str)
    except Exception:
        _LOG.exception("Failed calculating time window")

    daily_start = time.perf_counter()
    try:
        _run_main(["--ai"])
    except Exception as e:
        _LOG.exception("Daily generation failed: %s", e)
        raise
    daily_dur = time.perf_counter() - daily_start
    _LOG.info("Daily report generated successfully (%.2fs)", daily_dur)

    monthly_dur = 0.0
    if today.day <= 7 and _is_first_weekday_of_month(today):
        prev_month = _previous_month(today)
        _LOG.info("First weekday of month detected, generating monthly for %s", prev_month)
        monthly_start = time.perf_counter()
        try:
            _run_main(["--monthly", prev_month, "--ai"])
        except Exception as e:
            _LOG.exception("Monthly generation failed for %s: %s", prev_month, e)
        else:
            monthly_dur = time.perf_counter() - monthly_start
            _LOG.info("Monthly report generated successfully (%.2fs)", monthly_dur)

    total_dur = time.perf_counter() - start_ts
    _LOG.info(
        "Execution finished (total=%.2fs, daily=%.2fs, monthly=%.2fs)",
        total_dur,
        daily_dur,
        monthly_dur,
    )


if __name__ == "__main__":
    try:
        main()
    except Exception:
        sys.exit(1)
    sys.exit(0)
