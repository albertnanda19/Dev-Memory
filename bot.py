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
from range_aggregator import get_repo_achievements_in_range


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


def _short_hash(h: str) -> str:
    s = (h or "").strip()
    return s[:7] if len(s) >= 7 else s


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


def _split_messages(text: str, *, limit: int = 1800) -> list[str]:
    t = (text or "").strip()
    if not t:
        return [""]
    if len(t) <= limit:
        return [t]

    lines = t.splitlines()
    out: list[str] = []
    buf: list[str] = []

    def _flush():
        nonlocal buf
        if not buf:
            return
        out.append("\n".join(buf).strip())
        buf = []

    for ln in lines:
        cand = "\n".join(buf + [ln]).strip()
        if len(cand) <= limit:
            buf.append(ln)
            continue
        if buf:
            _flush()
        if len(ln) <= limit:
            buf.append(ln)
            continue
        chunk = ln
        while chunk:
            out.append(chunk[:limit].rstrip())
            chunk = chunk[limit:]

    _flush()
    if len(out) > 1:
        adjusted: list[str] = []
        for idx, m in enumerate(out):
            if idx == 0:
                adjusted.append(m)
            else:
                adjusted.append(m + "\n\n(lanjutan...)")
        return adjusted
    return out


async def _send_with_retries(
    interaction: discord.Interaction,
    message: str,
    *,
    allowed_mentions: discord.AllowedMentions,
    retries: int = 3,
) -> None:
    attempt = 0
    last_err: Exception | None = None
    while attempt < retries:
        attempt += 1
        try:
            await interaction.followup.send(message, allowed_mentions=allowed_mentions)
            return
        except Exception as e:
            last_err = e
            _LOG.warning(
                "bot_send_failed attempt=%s err=%s",
                attempt,
                str(e),
            )
            await asyncio.sleep(0.5 * attempt)
    if last_err is not None:
        raise last_err


def _validate_repo_integrity(repo: dict[str, Any]) -> None:
    name = str(repo.get("name") or "")
    expected = int(repo.get("commit_count_expected") or 0)
    count = int(repo.get("commit_count") or 0)
    detailed = repo.get("detailed_commits")
    detailed_count = len(detailed) if isinstance(detailed, list) else 0
    if expected != count or count != detailed_count:
        _LOG.error(
            "bot_integrity_mismatch repo=%s expected=%s count=%s detailed=%s",
            name,
            expected,
            count,
            detailed_count,
        )
        raise RuntimeError(
            f"integrity mismatch repo={name} expected={expected} count={count} detailed={detailed_count}"
        )


def _build_repo_commit_list(repo: dict[str, Any]) -> str:
    commits = repo.get("detailed_commits")
    if not isinstance(commits, list) or not commits:
        return ""

    lines: list[str] = []
    lines.append("### Daftar Commit")
    for c in commits:
        if not isinstance(c, dict):
            continue
        h = _short_hash(str(c.get("hash") or ""))
        msg = str(c.get("message") or "").strip()
        files = c.get("files")
        file_paths = []
        if isinstance(files, list):
            for f in files:
                if not isinstance(f, dict):
                    continue
                p = f.get("path")
                if isinstance(p, str) and p.strip():
                    file_paths.append(p.strip())
        file_paths = sorted(set(file_paths))
        if file_paths:
            file_preview = ", ".join(file_paths[:8])
            suffix = "" if len(file_paths) <= 8 else " ..."
            if msg:
                lines.append(f"- `{h}` {msg} ({file_preview}{suffix})")
            else:
                lines.append(f"- `{h}` ({file_preview}{suffix})")
        else:
            if msg:
                lines.append(f"- `{h}` {msg}")
            else:
                lines.append(f"- `{h}`")
    return "\n".join(lines).strip()


def _build_repo_ai_prompt(repo: dict[str, Any], *, start_date: str, end_date: str) -> str:
    data = {
        "period": {"start_date": start_date, "end_date": end_date},
        "repository": {
            "name": repo.get("name"),
            "commits": repo.get("detailed_commits") or [],
            "detailed_changes": repo.get("detailed_changes") or [],
            "files_by_directory": repo.get("files_by_directory") or {},
        },
    }

    return "\n".join(
        [
            "Tulis Daily Standup untuk 1 repository saja. Jangan campur repository lain.",
            "Gunakan Bahasa Indonesia yang natural. Technical terms tetap English.",
            "Mulai setiap bullet dengan 'Saya ...'.",
            "",
            "Fokus pada perubahan yang benar-benar saya lakukan berdasarkan commit list.",
            "Jangan menghilangkan konteks penting. Jangan generik.",
            "",
            "Data (lossless):",
            json.dumps(data, indent=2),
            "",
            "Aturan output:",
            "- Gunakan heading persis seperti format.",
            "- Minimal 5 dan maksimal 8 bullet aksi konkret.",
            "- Jangan sebut metric atau angka apa pun.",
            "",
            "Format:",
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


def _ai_output_is_valid_repo(text: str) -> bool:
    t = (text or "").strip()
    if not t:
        return False
    low = t.lower()
    if any(ch.isdigit() for ch in t):
        return False
    banned = ["executive summary", "commit", "commits", "insertions", "deletions", "file count", "files changed"]
    if any(b in low for b in banned):
        return False
    required_headings = [
        "### yang saya kerjakan",
        "### yang saya tingkatkan",
        "### safeguard & quality",
        "### fokus berikutnya",
    ]
    if not all(h in low for h in required_headings):
        return False
    bullets = [ln.strip() for ln in t.splitlines() if ln.strip().startswith("-")]
    saya_bullets = [ln for ln in bullets if ln.lower().startswith("- saya ")]
    if len(saya_bullets) < 5 or len(bullets) > 8:
        return False
    return True


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

    agg = await asyncio.to_thread(get_repo_achievements_in_range, start_date, end_date)
    repositories = agg.get("repositories")
    if not isinstance(repositories, list):
        repositories = []

    if not repositories:
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

    for repo in repositories:
        if isinstance(repo, dict):
            _validate_repo_integrity(repo)

    client = None
    if _ai_enabled():
        try:
            client = await asyncio.to_thread(_load_ai_client)
        except Exception as e:
            _LOG.warning("bot_ai_client_load_failed err=%s", str(e))
            client = None

    repo_blocks: list[str] = []
    for repo in repositories:
        if not isinstance(repo, dict):
            continue
        repo_name = str(repo.get("name") or "").strip()
        if not repo_name:
            continue

        expected = int(repo.get("commit_count_expected") or 0)
        note = f"Catatan: Total commit dalam periode ini: {expected}. Semua commit telah diproses."

        ai_text = ""
        ai_latency_ms: int | None = None
        if client is not None:
            ai_t0 = time.perf_counter()
            try:
                prompt = _build_repo_ai_prompt(repo, start_date=start_date, end_date=end_date)
                candidate = await asyncio.to_thread(client.generate_ai_summary, prompt)
                if not _ai_output_is_valid_repo(candidate):
                    retry_prompt = _build_ai_retry_prompt(candidate)
                    candidate = await asyncio.to_thread(client.generate_ai_summary, retry_prompt)
                if _ai_output_is_valid_repo(candidate):
                    ai_text = candidate.strip()
            except Exception as e:
                _LOG.warning(
                    "bot_cmd_ai_failed name=achievement-range repo=%s err=%s",
                    repo_name,
                    str(e),
                )
                ai_text = ""
            ai_latency_ms = int((time.perf_counter() - ai_t0) * 1000)

        if not ai_text:
            ai_text = _build_non_ai_standup(repo)

        commit_list = _build_repo_commit_list(repo)
        block_parts = [f"## Repository: {repo_name}", "", note, "", ai_text.strip()]
        if commit_list:
            block_parts.extend(["", commit_list])
        repo_blocks.append("\n".join(block_parts).strip())

        _LOG.info(
            "bot_repo_summary_done repo=%s ai_ms=%s",
            repo_name,
            ai_latency_ms,
        )

    full_message = header + "\n\n" + "\n\n---\n\n".join(repo_blocks)

    total_dur_ms = int((time.perf_counter() - start_ts) * 1000)
    _LOG.info(
        "bot_cmd_done name=achievement-range user_id=%s start=%s end=%s dur_ms=%s ai_ms=%s",
        user_id,
        start_date,
        end_date,
        total_dur_ms,
        None,
    )

    allowed = discord.AllowedMentions(users=True)
    chunks = _split_messages(full_message, limit=1800)
    for idx, chunk in enumerate(chunks):
        msg = chunk
        if idx != 0:
            msg = msg.replace(interaction.user.mention, "").lstrip()
        await _send_with_retries(interaction, msg, allowed_mentions=allowed, retries=3)
        await asyncio.sleep(0.5)


def run_bot() -> None:
    token = _env_any("DISCORD_BOT_TOKEN")
    if not token:
        raise RuntimeError("DISCORD_BOT_TOKEN is required")
    _client.run(token)
