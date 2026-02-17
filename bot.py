from __future__ import annotations

import asyncio
import datetime as _dt
import json
import os
import time
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from typing import Any

import discord
from discord import app_commands

from logger import get_logger
from range_aggregator import aggregate_reports, get_reports_in_range


_LOG = get_logger()


def _env(name: str) -> str:
    return (os.getenv(name) or "").strip()


def _load_dotenv_vars() -> dict[str, str]:
    env_path = Path(__file__).resolve().parent / ".env"
    if not env_path.exists():
        return {}
    try:
        content = env_path.read_text(encoding="utf-8")
    except Exception:
        return {}
    out: dict[str, str] = {}
    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("#"):
            continue
        if "=" not in line:
            continue
        k, v = line.split("=", 1)
        k = k.strip()
        v = v.strip().strip('"').strip("'")
        if k:
            out[k] = v
    return out


_DOTENV = _load_dotenv_vars()


def _env_any(name: str) -> str:
    v = _env(name)
    if v:
        return v
    return (_DOTENV.get(name) or "").strip()


def _parse_date(date_str: str) -> _dt.date:
    return _dt.datetime.strptime(date_str, "%Y-%m-%d").date()


def _load_ai_client():
    mod_path = Path(__file__).resolve().parent / "llm-client.py"
    spec = spec_from_file_location("dev_memory_llm_client", mod_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load llm-client.py")
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _ai_enabled() -> bool:
    if _env_any("LLM_API_URL") and _env_any("LLM_API_KEY"):
        return True
    if _env_any("GEMINI_API_KEY"):
        return True
    return False


def _build_structured_markdown(agg: dict[str, Any]) -> str:
    period = f"{agg.get('start_date', '')} → {agg.get('end_date', '')}".strip()
    if period == "→" or period == "":
        period = ""

    top_dirs = agg.get("top_directories") or []
    top_ext = agg.get("top_file_types") or []

    parts: list[str] = []
    parts.append("# Achievement Summary")
    if period:
        parts.append(f"Period: {period}")
    parts.append(f"Total Days: {int(agg.get('total_days', 0) or 0)}")
    parts.append("")
    parts.append(f"Commits: {int(agg.get('total_commits', 0) or 0)}")
    parts.append(f"Files Changed: {int(agg.get('total_files_changed', 0) or 0)}")
    parts.append(f"Insertions: {int(agg.get('total_insertions', 0) or 0)}")
    parts.append(f"Deletions: {int(agg.get('total_deletions', 0) or 0)}")
    parts.append("")

    parts.append("Top Directories:")
    if top_dirs:
        for idx, v in enumerate(top_dirs[:10], start=1):
            parts.append(f"{idx}. {v}")
    else:
        parts.append("(none)")
    parts.append("")

    parts.append("Top File Types:")
    if top_ext:
        for idx, v in enumerate(top_ext[:10], start=1):
            parts.append(f"{idx}. {v}")
    else:
        parts.append("(none)")

    return "\n".join(parts).strip()


def _build_ai_prompt(agg: dict[str, Any]) -> str:
    return "\n".join(
        [
            "You are a senior software engineer writing a professional achievement summary.",
            "",
            "Use only the structured data below.",
            json.dumps(agg, indent=2),
            "",
            "Write output in English:",
            "- 1 short executive summary paragraph",
            "- 3-5 bullet insights",
            "- 1 suggested focus area for next period",
            "",
            "Rules:",
            "- Do not invent metrics",
            "- Do not exaggerate",
            "- Use only the given data",
        ]
    )


def _validate_range(*, start_date: str, end_date: str) -> tuple[_dt.date, _dt.date, str | None]:
    try:
        start = _parse_date(start_date)
        end = _parse_date(end_date)
    except ValueError:
        return _dt.date.min, _dt.date.min, "Invalid date format. Use YYYY-MM-DD."

    if start > end:
        return start, end, "Invalid range. start_date must be <= end_date."

    today = _dt.date.today()
    if start > today or end > today:
        return start, end, "Dates in the future are not allowed."

    if (end - start).days > 365:
        return start, end, "Range too large. Maximum allowed is 365 days."

    return start, end, None


class DevMemoryClient(discord.Client):
    def __init__(self) -> None:
        intents = discord.Intents.none()
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self) -> None:
        await self.tree.sync()


_client = DevMemoryClient()


@_client.tree.command(name="achievement-range", description="Generate an achievement summary for a date range")
@app_commands.describe(start_date="YYYY-MM-DD", end_date="YYYY-MM-DD")
async def achievement_range(interaction: discord.Interaction, start_date: str, end_date: str):
    start_ts = time.perf_counter()
    user_id = str(getattr(getattr(interaction, "user", None), "id", ""))

    start, end, err = _validate_range(start_date=start_date, end_date=end_date)
    if err:
        _LOG.info(
            "bot_cmd_invalid user_id=%s start=%s end=%s err=%s",
            user_id,
            start_date,
            end_date,
            err,
        )
        await interaction.response.send_message(err, ephemeral=True)
        return

    await interaction.response.defer(thinking=True)

    _LOG.info(
        "bot_cmd_start name=achievement-range user_id=%s start=%s end=%s",
        user_id,
        start_date,
        end_date,
    )

    reports = await asyncio.to_thread(get_reports_in_range, start_date, end_date)
    agg = await asyncio.to_thread(aggregate_reports, reports)
    agg["start_date"] = start_date
    agg["end_date"] = end_date
    agg["total_days"] = int((end - start).days) + 1

    if not reports or int(agg.get("total_commits", 0) or 0) == 0:
        total_dur_ms = int((time.perf_counter() - start_ts) * 1000)
        _LOG.info(
            "bot_cmd_empty name=achievement-range user_id=%s start=%s end=%s dur_ms=%s",
            user_id,
            start_date,
            end_date,
            total_dur_ms,
        )
        await interaction.followup.send(
            f"{interaction.user.mention}\nNo development activity found in selected range.",
            allowed_mentions=discord.AllowedMentions(users=True),
        )
        return

    structured = _build_structured_markdown(agg)
    message = f"{interaction.user.mention}\n```\n{structured}\n```"

    ai_text = ""
    ai_latency_ms: int | None = None
    if _ai_enabled():
        ai_t0 = time.perf_counter()
        try:
            prompt = _build_ai_prompt(agg)
            client = await asyncio.to_thread(_load_ai_client)
            ai_text = await asyncio.to_thread(client.generate_ai_summary, prompt)
        except Exception as e:
            _LOG.warning(
                "bot_cmd_ai_failed name=achievement-range user_id=%s err=%s",
                user_id,
                str(e),
            )
            ai_text = ""
        ai_latency_ms = int((time.perf_counter() - ai_t0) * 1000)

    if ai_text.strip():
        message = message + "\n\nAI Insight:\n" + ai_text.strip()

    total_dur_ms = int((time.perf_counter() - start_ts) * 1000)
    _LOG.info(
        "bot_cmd_done name=achievement-range user_id=%s start=%s end=%s dur_ms=%s ai_ms=%s",
        user_id,
        start_date,
        end_date,
        total_dur_ms,
        ai_latency_ms,
    )

    await interaction.followup.send(
        message,
        allowed_mentions=discord.AllowedMentions(users=True),
    )


def run_bot() -> None:
    token = _env_any("DISCORD_BOT_TOKEN")
    if not token:
        raise RuntimeError("DISCORD_BOT_TOKEN is required")
    _client.run(token)
