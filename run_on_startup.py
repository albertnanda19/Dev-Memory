from __future__ import annotations

import datetime as _dt
import subprocess
import sys
from pathlib import Path

from logger import get_logger
from state_manager import get_last_execution_date


_LOG = get_logger()


def _project_root() -> Path:
    return Path(__file__).resolve().parent


def _compute_logical_report_date(now: _dt.datetime) -> str | None:
    # Recovery only makes sense after the scheduled 06:00 cut-off.
    if now.time() < _dt.time(hour=6, minute=0):
        return None

    today = now.date()
    # Label is always yesterday (Sunday when today is Monday)
    label_day = today - _dt.timedelta(days=1)
    return label_day.strftime("%Y-%m-%d")


def _daily_json_path(date_str: str) -> Path:
    return _project_root() / "data" / "daily" / f"{date_str}.json"


def main() -> int:
    _LOG.info("Startup detected")

    now = _dt.datetime.now()
    date_str = _compute_logical_report_date(now)
    if not date_str:
        _LOG.info("Startup before 06:00, no recovery needed")
        return 0

    last = get_last_execution_date()
    if last == date_str:
        _LOG.info("Already executed for %s (state), exit", date_str)
        return 0

    if _daily_json_path(date_str).exists():
        _LOG.info("Daily JSON already exists for %s, exit", date_str)
        return 0

    _LOG.warning("Missed scheduled 06:00 execution detected")
    _LOG.info("Running recovery job")

    cmd = [sys.executable, str(_project_root() / "run_daily.py")]
    cp = subprocess.run(
        cmd,
        cwd=str(_project_root()),
        capture_output=True,
        text=True,
        check=False,
    )
    if cp.returncode != 0:
        _LOG.error(
            "Recovery job failed (rc=%s): %s",
            cp.returncode,
            (cp.stderr or cp.stdout or "").strip(),
        )
        return 1

    _LOG.info("Recovery completed successfully")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
