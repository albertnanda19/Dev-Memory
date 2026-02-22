from __future__ import annotations

import datetime as _dt
import os
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from zoneinfo import ZoneInfo


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


def env_any(name: str) -> str:
    v = _env(name)
    if v:
        return v
    return (_DOTENV.get(name) or "").strip()


def env_int(name: str, default: int) -> int:
    raw = env_any(name)
    if not raw:
        return default
    try:
        return int(raw)
    except Exception:
        return default


def parse_wib_datetime(value: str) -> _dt.datetime:
    s = (value or "").strip()
    dt = _dt.datetime.strptime(s, "%Y-%m-%d %H:%M")
    return dt.replace(tzinfo=ZoneInfo("Asia/Jakarta"))


def to_git_ts(dt: _dt.datetime) -> str:
    return dt.astimezone(_dt.timezone.utc).isoformat(timespec="minutes")


def validate_window(*, since: str, until: str) -> tuple[_dt.datetime, _dt.datetime, str | None]:
    try:
        since_dt = parse_wib_datetime(since)
        until_dt = parse_wib_datetime(until)
    except ValueError:
        z = _dt.timezone.utc
        return _dt.datetime.min.replace(tzinfo=z), _dt.datetime.min.replace(tzinfo=z), "Invalid datetime format. Use YYYY-MM-DD HH:MM (WIB)."

    if since_dt >= until_dt:
        return since_dt, until_dt, "Invalid window. since must be earlier than until."

    max_days = 365
    if (until_dt - since_dt).days > max_days:
        return since_dt, until_dt, f"Window too large. Maximum allowed is {max_days} days."

    now = _dt.datetime.now(tz=ZoneInfo("Asia/Jakarta"))
    if since_dt > now or until_dt > now:
        return since_dt, until_dt, "Datetimes in the future are not allowed."

    return since_dt, until_dt, None


def load_ai_client():
    mod_path = Path(__file__).resolve().parent / "llm-client.py"
    spec = spec_from_file_location("dev_memory_llm_client", mod_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load llm-client.py")
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def ai_enabled() -> bool:
    if env_any("LLM_API_URL") and env_any("LLM_API_KEY"):
        return True
    if env_any("GEMINI_API_KEY"):
        return True
    return False


def split_repo_block(*, repo_name: str, task_lines: list[str], limit: int = 1800) -> list[str]:
    heading = f"## Repository: {repo_name}".strip()
    lines = [heading, *[ln.rstrip() for ln in (task_lines or []) if (ln or "").strip()]]
    if not lines:
        return []

    chunks: list[list[str]] = []
    buf: list[str] = []

    def _buf_text(next_line: str | None = None) -> str:
        arr = buf if next_line is None else (buf + [next_line])
        return "\n".join(arr).strip()

    for idx, ln in enumerate(lines):
        if idx == 0:
            buf = [ln]
            continue

        cand = _buf_text(ln)
        if len(cand) <= limit:
            buf.append(ln)
            continue

        if len(buf) > 1:
            chunks.append(buf)
            buf = [heading, ln]
            continue

        chunks.append(buf)
        buf = [heading]
        if len(_buf_text(ln)) <= limit:
            buf.append(ln)
            continue

        if ln.strip().startswith("- "):
            chunks.append([heading, ln[: max(0, limit - len(heading) - 1)]])
        else:
            chunks.append([ln[:limit]])
        buf = [heading]

    if buf:
        chunks.append(buf)

    out: list[str] = []
    for cidx, c in enumerate(chunks):
        text = "\n".join(c).strip()
        if cidx > 0:
            text = text + "\n\n(lanjutan...)"
        out.append(text)

    return out


def build_repo_task_lines_non_ai(repo: dict[str, object]) -> list[str]:
    commits = repo.get("detailed_commits")
    if not isinstance(commits, list) or not commits:
        return []

    def _clean_commit_message(msg: str) -> str:
        s = (msg or "").strip()
        low = s.lower()
        prefixes = ["feat:", "fix:", "refactor:", "test:", "chore:", "perf:", "ci:"]
        for p in prefixes:
            if low.startswith(p):
                return s[len(p) :].strip()
        return s

    out: list[str] = []
    for c in commits:
        if not isinstance(c, dict):
            continue
        msg = _clean_commit_message(str(c.get("message") or "")).strip()
        if not msg:
            msg = "melakukan perubahan kode"
        out.append(f"- Saya {msg}")

    return out
