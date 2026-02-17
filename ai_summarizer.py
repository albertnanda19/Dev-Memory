from __future__ import annotations

import concurrent.futures
import hashlib
import time
from dataclasses import dataclass
from typing import Any

from logger import get_logger


_LOG = get_logger()


@dataclass(frozen=True)
class RepoLLMResult:
    ok: bool
    repo_name: str
    bullet_lines: list[str]
    token_estimate: int
    retries: int
    latency_s: float
    error: str


_CACHE: dict[str, RepoLLMResult] = {}


def _estimate_tokens(text: str) -> int:
    t = (text or "").strip()
    if not t:
        return 0
    return max(1, len(t) // 4)


def _truncate_commit_message(msg: str, *, max_len: int) -> str:
    s = (msg or "").strip()
    if max_len <= 0:
        return ""
    if len(s) <= max_len:
        return s
    cut = s[:max_len].rstrip()
    if not cut:
        return s[:max_len]
    return cut


def _commit_signature(commits: list[dict[str, Any]]) -> str:
    h = hashlib.sha256()
    for c in commits:
        if not isinstance(c, dict):
            continue
        ch = str(c.get("hash") or "").strip()
        msg = str(c.get("message") or "").strip()
        h.update(ch.encode("utf-8", errors="ignore"))
        h.update(b"\n")
        h.update(msg.encode("utf-8", errors="ignore"))
        h.update(b"\n")
    return h.hexdigest()


def _cache_key(*, repo_name: str, start_date: str, end_date: str, commits: list[dict[str, Any]]) -> str:
    sig = _commit_signature(commits)
    raw = f"{repo_name}|{start_date}|{end_date}|{sig}"
    return hashlib.sha256(raw.encode("utf-8", errors="ignore")).hexdigest()


def _extract_bullets(text: str) -> list[str]:
    t = (text or "").strip()
    if not t:
        return []
    lines = [ln.rstrip() for ln in t.splitlines() if ln.strip()]
    bullets = [ln for ln in lines if ln.lstrip().startswith("-")]
    out: list[str] = []
    for b in bullets:
        s = b.strip()
        if not s.startswith("- "):
            if s.startswith("-"):
                s = "- " + s[1:].lstrip()
        if s.lower().startswith("- saya "):
            out.append(s)
            continue
        if s.lower().startswith("-saya "):
            out.append("- Saya " + s[6:].lstrip())
            continue
        if s.lower().startswith("- saya"):
            out.append("- Saya " + s[6:].lstrip())
            continue
    return out


def _build_prompt(
    *,
    repo_name: str,
    start_date: str,
    end_date: str,
    commits: list[dict[str, Any]],
    max_message_len: int,
) -> str:
    period = f"{start_date} → {end_date}"
    parts: list[str] = []
    parts.append("Tulis daftar bullet Daily Standup untuk 1 repository saja.")
    parts.append("Gunakan Bahasa Indonesia yang natural. Technical terms tetap English.")
    parts.append("Setiap bullet harus dimulai dengan '- Saya ...'.")
    parts.append("Aturan wajib:")
    parts.append("- Satu commit menghasilkan tepat satu bullet.")
    parts.append("- Jangan menggabungkan beberapa commit menjadi satu bullet.")
    parts.append("- Jangan menghapus commit kecil.")
    parts.append("- Jangan menambahkan angka/metric.")
    parts.append("")
    parts.append(f"Repository: {repo_name}")
    parts.append(f"Periode: {period}")
    parts.append("")
    parts.append("Commit List (urut sesuai input):")

    idx = 0
    for c in commits:
        if not isinstance(c, dict):
            continue
        idx += 1
        ch = str(c.get("hash") or "").strip()
        msg = _truncate_commit_message(str(c.get("message") or ""), max_len=max_message_len)
        parts.append(f"{idx}. {ch} | {msg}")

    parts.append("")
    parts.append("Output hanya berupa bullet list tanpa heading.")
    return "\n".join(parts).strip()


def _compute_max_message_len(*, commit_count: int, token_budget: int) -> int:
    if commit_count <= 0:
        return 120
    base_overhead = 400
    per_commit_overhead = 40
    available = max(0, token_budget - base_overhead - (commit_count * per_commit_overhead))
    per_commit_tokens = max(10, available // commit_count)
    return max(40, min(220, per_commit_tokens * 4))


def summarize_repo_once(
    *,
    ai_client: Any,
    repo_name: str,
    start_date: str,
    end_date: str,
    commits: list[dict[str, Any]],
    token_budget: int,
) -> tuple[str, int]:
    max_len = _compute_max_message_len(commit_count=len(commits), token_budget=token_budget)
    prompt = _build_prompt(
        repo_name=repo_name,
        start_date=start_date,
        end_date=end_date,
        commits=commits,
        max_message_len=max_len,
    )
    return prompt, _estimate_tokens(prompt)


def summarize_repo(
    *,
    ai_client: Any,
    repo_name: str,
    start_date: str,
    end_date: str,
    commits: list[dict[str, Any]],
    max_retries: int = 2,
    timeout_s: int = 30,
    token_budget: int = 6000,
    use_cache: bool = True,
) -> RepoLLMResult:
    t0 = time.perf_counter()
    commit_count = len(commits)
    key = _cache_key(repo_name=repo_name, start_date=start_date, end_date=end_date, commits=commits)
    if use_cache:
        cached = _CACHE.get(key)
        if cached is not None and cached.ok:
            _LOG.info(
                "llm_repo_request repo=%s commits=%s token_est=%s retries=%s latency_s=%.2f status=CACHE_HIT",
                repo_name,
                commit_count,
                cached.token_estimate,
                cached.retries,
                cached.latency_s,
            )
            return cached

    prompt, token_est = summarize_repo_once(
        ai_client=ai_client,
        repo_name=repo_name,
        start_date=start_date,
        end_date=end_date,
        commits=commits,
        token_budget=token_budget,
    )

    retries = 0
    last_err = ""
    text = ""

    while True:
        attempt_t0 = time.perf_counter()
        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
                fut = ex.submit(ai_client.generate_ai_summary, prompt)
                text = fut.result(timeout=timeout_s)
            text = (text or "").strip()
            attempt_latency = time.perf_counter() - attempt_t0
            _LOG.info(
                "llm_repo_attempt repo=%s commits=%s token_est=%s retries=%s latency_s=%.2f",
                repo_name,
                commit_count,
                token_est,
                retries,
                attempt_latency,
            )
        except Exception as e:
            last_err = str(e)
            if retries >= max_retries:
                break
            wait_s = min(4.0, 0.5 * (2**retries))
            _LOG.warning(
                "llm_repo_retry repo=%s commits=%s token_est=%s retry=%s wait_s=%.2f err=%s",
                repo_name,
                commit_count,
                token_est,
                retries + 1,
                wait_s,
                last_err,
            )
            time.sleep(wait_s)
            retries += 1
            continue

        bullets = _extract_bullets(text)
        if len(bullets) >= commit_count:
            latency_s = time.perf_counter() - t0
            res = RepoLLMResult(
                ok=True,
                repo_name=repo_name,
                bullet_lines=bullets[:commit_count],
                token_estimate=token_est,
                retries=retries,
                latency_s=latency_s,
                error="",
            )
            if use_cache:
                _CACHE[key] = res
            _LOG.info(
                "llm_repo_request repo=%s commits=%s token_est=%s retries=%s latency_s=%.2f status=SUCCESS",
                repo_name,
                commit_count,
                token_est,
                retries,
                latency_s,
            )
            return res

        if retries >= max_retries:
            last_err = f"invalid bullet coverage bullets={len(bullets)} commits={commit_count}"
            break

        _LOG.warning(
            "llm_repo_regen repo=%s commits=%s token_est=%s retry=%s bullets=%s",
            repo_name,
            commit_count,
            token_est,
            retries + 1,
            len(bullets),
        )
        retries += 1
        continue

    latency_s = time.perf_counter() - t0
    res = RepoLLMResult(
        ok=False,
        repo_name=repo_name,
        bullet_lines=[],
        token_estimate=token_est,
        retries=retries,
        latency_s=latency_s,
        error=last_err or "LLM request failed",
    )
    _LOG.error(
        "llm_repo_request repo=%s commits=%s token_est=%s retries=%s latency_s=%.2f status=FAILED err=%s",
        repo_name,
        commit_count,
        token_est,
        retries,
        latency_s,
        res.error,
    )
    return res
