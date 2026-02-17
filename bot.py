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

    def _clean_desc(desc: str) -> str:
        d = desc.strip()
        low = d.lower()
        prefixes = ["feat:", "fix:", "refactor:", "test:", "chore:", "perf:", "ci:"]
        for p in prefixes:
            if low.startswith(p):
                return d[len(p) :].strip()
        return d

    if built:
        sections.append("### Yang Saya Kerjakan")
        for it in built:
            desc = _clean_desc(str(it.get("description") or ""))
            if desc:
                sections.append(f"- Saya {desc}")
        sections.append("")

    if improved:
        sections.append("### Yang Saya Tingkatkan")
        for it in improved:
            desc = _clean_desc(str(it.get("description") or ""))
            if desc:
                sections.append(f"- Saya {desc}")
        sections.append("")

    if safeguards:
        sections.append("### Safeguard & Quality")
        for it in safeguards:
            desc = _clean_desc(str(it.get("description") or ""))
            if desc:
                sections.append(f"- Saya {desc}")
        sections.append("")

    if not built and not improved and not safeguards:
        sections.append("No development activity found in selected range.")

    return "\n".join(sections).strip()


def _build_ai_prompt(agg: dict[str, Any]) -> str:
    return "\n".join(
        [
            "Tulis Daily Standup dalam Bahasa Indonesia yang natural untuk software engineer.",
            "Gunakan sudut pandang first person dan mulai setiap bullet dengan 'Saya ...'.",
            "",
            "Gunakan Bahasa Indonesia sebagai bahasa utama.",
            "Biarkan technical terms tetap dalam English (contoh: endpoint, validation, middleware, refactor, transaction, service layer, redirect, database, integration, performance).",
            "Jangan menerjemahkan technical terms kalau membuatnya jadi tidak natural.",
            "",
            "Hindari awkward literal translation.",
            "Hindari tone akademik / blog.",
            "Hindari corporate buzzwords.",
            "",
            "Fokus pada execution narrative: apa yang saya build/ubah, problem apa yang saya selesaikan, keputusan teknis apa yang saya buat, safeguard apa yang saya tambah.",
            "Jelaskan seperlunya alasan teknis tanpa berubah jadi dokumentasi.",
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
            "Aturan output:",
            "- Gunakan Markdown heading persis seperti format di bawah.",
            "- Minimal 5 dan maksimal 8 bullet aksi yang konkret (total across sections).",
            "- Hindari kalimat generik seperti 'Saya mengoptimalkan sistem' tanpa konteks. Jelaskan apa yang diubah.",
            "- Jangan sebut metric atau angka apa pun (commit, insertions, deletions, file count, dll).",
            "- Jangan gunakan phrase seperti 'Executive Summary'.",
            "",
            "Structure:",
            "### Yang Saya Kerjakan",
            "- Saya ...",
            "",
            "### Yang Saya Tingkatkan",
            "- Saya ...",
            "",
            "### Safeguard & Quality",
            "- Saya ...",
            "",
            "### Fokus Berikutnya",
            "- Saya ...",
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
        "mengoptimalkan sistem",
        "meningkatkan performa secara keseluruhan",
        "mengembangkan fitur baru",
    ]
    if any(g in low for g in generic):
        return False

    bullets = [ln.strip() for ln in t.splitlines() if ln.strip().startswith("-")]
    saya_bullets = [ln for ln in bullets if ln.lower().startswith("- saya ")]
    if len(saya_bullets) < 5:
        return False

    if len(bullets) > 8:
        return False

    action_words = [
        "menambahkan",
        "membuat",
        "mengimplementasikan",
        "mengintegrasikan",
        "memperbaiki",
        "menyelesaikan",
        "melakukan refactor",
        "merapikan",
        "menyederhanakan",
        "menambahkan validation",
        "menambahkan error handling",
        "memastikan",
        "mengoptimalkan",
        "mengonfigurasi",
        "mengotomasi",
    ]
    action_like = [ln for ln in saya_bullets if any(w in ln.lower() for w in action_words)]
    if len(action_like) < 5:
        return False

    required_headings = [
        "### yang saya kerjakan",
        "### yang saya tingkatkan",
        "### safeguard & quality",
        "### fokus berikutnya",
    ]
    if not all(h in low for h in required_headings):
        return False

    if " saya " not in low:
        return False

    return True


def _build_ai_retry_prompt(previous_text: str) -> str:
    return "\n".join(
        [
            "Tulis ulang output Daily Standup dan patuhi aturan dengan ketat.",
            "",
            "Aturan wajib:",
            "- Bahasa Indonesia natural (bukan terjemahan literal).",
            "- Technical terms tetap English.",
            "- Setiap bullet harus dimulai dengan 'Saya ...'.",
            "- Minimal 5 dan maksimal 8 bullet aksi konkret.",
            "- Tidak boleh ada angka atau metric (commit/insertions/deletions/file count).",
            "- Hindari buzzword dan kalimat generik tanpa detail.",
            "",
            "Output sebelumnya (invalid):",
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
