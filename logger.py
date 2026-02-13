from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path


_LOGGER_NAME = "dev-memory"


class _IsoFormatter(logging.Formatter):
    def formatTime(self, record: logging.LogRecord, datefmt: str | None = None) -> str:
        dt = datetime.fromtimestamp(record.created)
        return dt.isoformat(timespec="seconds")


def get_logger() -> logging.Logger:
    logger = logging.getLogger(_LOGGER_NAME)
    if getattr(logger, "_dev_memory_configured", False):
        return logger

    logger.setLevel(logging.INFO)
    logger.propagate = False

    logs_dir = Path(__file__).resolve().parent / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_path = logs_dir / f"cron-{datetime.now().date().isoformat()}.log"

    handler = logging.FileHandler(log_path, encoding="utf-8")
    handler.setLevel(logging.INFO)
    handler.setFormatter(
        _IsoFormatter("[%(asctime)s] [%(levelname)s] [%(module)s] %(message)s")
    )
    logger.addHandler(handler)

    logger._dev_memory_configured = True  # type: ignore[attr-defined]
    return logger
