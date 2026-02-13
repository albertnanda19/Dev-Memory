from __future__ import annotations

import datetime as _dt
import subprocess
import sys
from pathlib import Path


def _project_root() -> Path:
    return Path(__file__).resolve().parent


def _log_path() -> Path:
    logs_dir = _project_root() / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    return logs_dir / "cron.log"


def _log_error(msg: str) -> None:
    try:
        _log_path().open("a", encoding="utf-8").write(msg.rstrip("\n") + "\n")
    except Exception:
        pass


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
    subprocess.run(cmd, check=True, cwd=str(_project_root()))


def main() -> None:
    today = _today()
    if not _is_weekday(today):
        return

    try:
        _run_main(["--ai"])
    except Exception as e:
        _log_error(f"{_dt.datetime.now().isoformat()} daily failed: {e}")
        return

    if today.day <= 7 and _is_first_weekday_of_month(today):
        prev_month = _previous_month(today)
        try:
            _run_main(["--monthly", prev_month, "--ai"])
        except Exception as e:
            _log_error(
                f"{_dt.datetime.now().isoformat()} monthly failed for {prev_month}: {e}"
            )


if __name__ == "__main__":
    main()
