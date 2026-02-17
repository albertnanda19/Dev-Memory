from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from logger import get_logger

from .discord_client import DiscordResult, send_message_or_file


_LOG = get_logger()


@dataclass(frozen=True)
class DailyStats:
    repo_count: int
    total_commits: int
    files_changed: int


def _load_daily_stats(daily_json_path: Path) -> DailyStats:
    try:
        raw = daily_json_path.read_text(encoding="utf-8")
        data: Any = json.loads(raw or "{}")
        committed = data.get("committed") if isinstance(data, dict) else None
        if not isinstance(committed, list):
            return DailyStats(repo_count=0, total_commits=0, files_changed=0)

        repo_count = len(committed)
        total_commits = 0
        files_changed = 0
        for item in committed:
            if not isinstance(item, dict):
                continue
            cc = item.get("commits_count")
            fc = item.get("files_changed")
            if isinstance(cc, int):
                total_commits += cc
            if isinstance(fc, int):
                files_changed += fc

        return DailyStats(repo_count=repo_count, total_commits=total_commits, files_changed=files_changed)
    except FileNotFoundError:
        return DailyStats(repo_count=0, total_commits=0, files_changed=0)
    except Exception:
        _LOG.exception("Gagal membaca daily JSON untuk statistik Discord: %s", str(daily_json_path))
        return DailyStats(repo_count=0, total_commits=0, files_changed=0)


def send_daily_standup(*, date_str: str, markdown_path: Path, daily_json_path: Path) -> DiscordResult:
    if not markdown_path.exists():
        _LOG.warning("[DISCORD DELIVERY] Markdown file not found: %s", str(markdown_path))
        return DiscordResult(
            ok=False,
            status_code=None,
            latency_ms=None,
            error="markdown_not_found",
            retry_count=0,
        )

    try:
        md_bytes = markdown_path.read_bytes()
    except Exception as e:
        _LOG.exception("[DISCORD DELIVERY] Failed reading markdown: %s", e)
        return DiscordResult(
            ok=False,
            status_code=None,
            latency_ms=None,
            error=str(e),
            retry_count=0,
        )

    if not md_bytes:
        _LOG.warning("[DISCORD DELIVERY] Markdown file empty: %s", str(markdown_path))
        return DiscordResult(
            ok=False,
            status_code=None,
            latency_ms=None,
            error="markdown_empty",
            retry_count=0,
        )

    stats = _load_daily_stats(daily_json_path)

    title = f"📊 Daily Standup — {date_str}"
    header = "\n".join(
        [
            title,
            "",
            f"Repository: {stats.repo_count}",
            f"Total Commit: {stats.total_commits}",
            f"Files Changed: {stats.files_changed}",
            "",
            "Detail lengkap ada di file terlampir.",
        ]
    ).strip()

    mention_user_id = None
    try:
        import os

        mention_user_id = (os.getenv("DISCORD_USER_ID") or "").strip() or None
        if not mention_user_id:
            env_path = Path(__file__).resolve().parent.parent / ".env"
            if env_path.exists():
                for raw_line in env_path.read_text(encoding="utf-8").splitlines():
                    line = raw_line.strip()
                    if not line or line.startswith("#"):
                        continue
                    if not line.startswith("DISCORD_USER_ID="):
                        continue
                    mention_user_id = line.split("=", 1)[1].strip().strip('"').strip("'")
                    if mention_user_id:
                        break
    except Exception:
        mention_user_id = None

    md_text = md_bytes.decode("utf-8", errors="replace")
    use_attachment = len(md_text) > 1800

    content = header
    file_path = markdown_path if use_attachment else None
    if not use_attachment:
        content = header + "\n\n```\n" + md_text + "\n```"

    start_ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    _LOG.info("[DISCORD DELIVERY] Start: %s", start_ts)
    _LOG.info("[DISCORD DELIVERY] Payload Size: %s bytes", len(md_bytes))
    _LOG.info("[DISCORD DELIVERY] Message Length: %s chars", len(content))

    result = send_message_or_file(
        content=content,
        file_path=file_path,
        filename=markdown_path.name,
        mention_user_id=mention_user_id,
        retry_once=True,
    )

    if result.ok:
        follow_up = f"✅ Daily Standup berhasil dibuat dan dikirim pada {datetime.now().isoformat(timespec='seconds')}"
        _ = send_message_or_file(
            content=follow_up,
            file_path=None,
            filename=None,
            mention_user_id=mention_user_id,
            retry_once=True,
        )

    return result
