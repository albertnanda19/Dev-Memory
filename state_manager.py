from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from logger import get_logger


_LOG = get_logger()


def _state_path() -> Path:
    root = Path(__file__).resolve().parent
    data_dir = root / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir / "state.json"


def get_last_execution_date() -> str | None:
    path = _state_path()
    if not path.exists():
        return None

    try:
        raw = path.read_text(encoding="utf-8")
        data: Any = json.loads(raw or "{}")
        if isinstance(data, dict):
            value = data.get("last_daily_execution")
            if isinstance(value, str) and value.strip():
                return value.strip()
        return None
    except Exception:
        _LOG.exception("Gagal membaca state file: %s", str(path))
        return None


def set_last_execution_date(date_str: str) -> None:
    path = _state_path()

    try:
        payload = {"last_daily_execution": date_str}
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        tmp.replace(path)
    except Exception:
        _LOG.exception("Gagal menulis state file: %s", str(path))
