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


def _build_non_ai_standup(agg: dict[str, Any]) -> str:
    sections: list[str] = []

    items = agg.get("detailed_changes") or []
    if not isinstance(items, list):
        items = []

    by_type: dict[str, list[dict[str, Any]]] = {}
    for it in items:
        if not isinstance(it, dict):
            continue
        t = str(it.get("type") or "chore")
        arr = by_type.get(t)
        if arr is None:
            arr = []
            by_type[t] = arr
        arr.append(it)

    def _take(types: list[str], limit: int) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for t in types:
            out.extend(by_type.get(t) or [])
        return out[:limit]

    built = _take(["feature", "infra"], 6)
    improved = _take(["refactor", "performance"], 6)
    safeguards = _take(["validation", "test", "fix"], 6)

    if built:
        sections.append("### What I Built")
        for it in built:
            desc = str(it.get("description") or "").strip()
            if desc:
                sections.append(f"- {desc}")
        sections.append("")

    if improved:
        sections.append("### What I Improved")
        for it in improved:
            desc = str(it.get("description") or "").strip()
            if desc:
                sections.append(f"- {desc}")
        sections.append("")

    if safeguards:
        sections.append("### Safeguards & Quality")
        for it in safeguards:
            desc = str(it.get("description") or "").strip()
            if desc:
                sections.append(f"- {desc}")
        sections.append("")

    if not built and not improved and not safeguards:
        sections.append("No development activity found in selected range.")

    return "\n".join(sections).strip()


def _build_ai_prompt(agg: dict[str, Any]) -> str:
    return "\n".join(
        [
            "You are writing a real daily standup update as a software engineer.",
            "Write in first person (I ...).",
            "",
            "Use only the structured data below.",
            json.dumps(
                {
                    "period": {
                        "start_date": agg.get("start_date"),
                        "end_date": agg.get("end_date"),
                    },
                    "detailed_changes": agg.get("detailed_changes") or [],
                    "files_by_directory": agg.get("files_by_directory") or {},
                },
                indent=2,
            ),
            "",
            "Output requirements:",
            "- Use Markdown headings exactly as below.",
            "- Provide at least 4 concrete action statements across the sections.",
            "- Every bullet must describe an action taken (implemented/added/fixed/refactored/introduced/ensured/etc).",
            "- Be specific. Avoid generic phrases like 'worked across multiple components'.",
            "- Do not mention commits, insertions, deletions, file counts, or any numeric statistics.",
            "- Do not write 'Executive Summary'.",
            "",
            "Structure:",
            "## What I Built",
            "- ...",
            "",
            "## What I Improved",
            "- ...",
            "",
            "## Safeguards & Quality",
            "- ...",
            "",
            "## Notes / Next Focus",
            "- ...",
        ]
    )


def _ai_output_is_valid(text: str) -> bool:
    t = (text or "").strip()
    if not t:
        return False

    low = t.lower()
    banned = [
        "executive summary",
        "insertions",
        "deletions",
        "files changed",
        "file count",
        "commit",
        "commits",
        "high-volume",
    ]
    if any(b in low for b in banned):
        return False

    if any(ch.isdigit() for ch in t):
        return False

    generic = [
        "worked across",
        "various components",
        "multiple components",
        "improved overall",
        "general improvements",
    ]
    if any(g in low for g in generic):
        return False

    action_lines = [
        ln.strip()
        for ln in t.splitlines()
        if ln.strip().startswith("-")
        and any(
            v in ln.lower()
            for v in [
                "implemented",
                "added",
                "created",
                "integrated",
                "fixed",
                "resolved",
                "refactored",
                "simplified",
                "restructured",
                "introduced",
                "ensured",
                "validated",
                "optimized",
                "configured",
                "automated",
            ]
        )
    ]
    if len(action_lines) < 4:
        return False

    required_headings = [
        "## what i built",
        "## what i improved",
        "## safeguards & quality",
        "## notes / next focus",
    ]
    if not all(h in low for h in required_headings):
        return False

    return True


def _build_ai_retry_prompt(previous_text: str) -> str:
    return "\n".join(
        [
            "Rewrite the standup output and strictly follow the requirements.",
            "",
            "Hard rules:",
            "- No numbers.",
            "- No mention of commits, insertions, deletions, or file counts.",
            "- No 'Executive Summary'.",
            "- At least 4 action bullets starting with strong verbs.",
            "- Avoid generic statements.",
            "",
            "Previous output (invalid):",
            previous_text.strip(),
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

    if not reports or not (agg.get("detailed_changes") or []):
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

    period = f"{start_date} → {end_date}"
    header = f"{interaction.user.mention}\n\n## Daily Standup ({period})"

    ai_text = ""
    ai_latency_ms: int | None = None
    if _ai_enabled():
        ai_t0 = time.perf_counter()
        try:
            prompt = _build_ai_prompt(agg)
            client = await asyncio.to_thread(_load_ai_client)
            candidate = await asyncio.to_thread(client.generate_ai_summary, prompt)
            if not _ai_output_is_valid(candidate):
                retry_prompt = _build_ai_retry_prompt(candidate)
                candidate = await asyncio.to_thread(client.generate_ai_summary, retry_prompt)
            if _ai_output_is_valid(candidate):
                ai_text = candidate.strip()
        except Exception as e:
            _LOG.warning(
                "bot_cmd_ai_failed name=achievement-range user_id=%s err=%s",
                user_id,
                str(e),
            )
            ai_text = ""
        ai_latency_ms = int((time.perf_counter() - ai_t0) * 1000)

    if not ai_text:
        ai_text = _build_non_ai_standup(agg)

    message = header + "\n\n" + ai_text.strip()

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
