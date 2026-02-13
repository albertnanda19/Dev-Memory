
from __future__ import annotations

from pathlib import Path
import json
from typing import Any

from models import DailyReport


def save_daily_markdown(report: DailyReport, markdown: str) -> None:
    date_str = getattr(report, "date", "")
    base_dir = Path(__file__).resolve().parent
    daily_dir = base_dir / "data" / "daily"
    daily_dir.mkdir(parents=True, exist_ok=True)

    out_path = daily_dir / f"{date_str}.md"
    out_path.write_text(markdown.rstrip("\n") + "\n", encoding="utf-8")


def save_monthly_json(month: str, data: dict[str, Any]) -> None:
    base_dir = Path(__file__).resolve().parent
    monthly_dir = base_dir / "data" / "monthly"
    monthly_dir.mkdir(parents=True, exist_ok=True)

    out_path = monthly_dir / f"{month}.json"
    tmp_path = out_path.with_suffix(out_path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    tmp_path.replace(out_path)


def save_monthly_markdown(month: str, markdown: str) -> None:
    base_dir = Path(__file__).resolve().parent
    monthly_dir = base_dir / "data" / "monthly"
    monthly_dir.mkdir(parents=True, exist_ok=True)

    out_path = monthly_dir / f"{month}.md"
    out_path.write_text(markdown.rstrip("\n") + "\n", encoding="utf-8")
