from __future__ import annotations

import asyncio
import time
from typing import Any

from ai_summarizer import summarize_repo_async
from logger import get_logger
from range_aggregator import get_repo_achievements_in_window

from achievement_runtime import (
    ai_enabled,
    env_int,
    load_ai_client,
    split_repo_block,
    to_git_ts,
    validate_window,
    build_repo_task_lines_non_ai,
)


_LOG = get_logger()


def _validate_repo_integrity(repo: dict[str, Any]) -> None:
    name = str(repo.get("name") or "")
    expected = int(repo.get("commit_count_expected") or 0)
    count = int(repo.get("commit_count") or 0)
    detailed = repo.get("detailed_commits")
    detailed_count = len(detailed) if isinstance(detailed, list) else 0
    if expected != count or count != detailed_count:
        _LOG.error(
            "achievement_integrity_mismatch repo=%s expected=%s count=%s detailed=%s",
            name,
            expected,
            count,
            detailed_count,
        )
        raise RuntimeError(
            f"integrity mismatch repo={name} expected={expected} count={count} detailed={detailed_count}"
        )


def _repo_markdown(*, repo_name: str, bullets: list[str]) -> str:
    blocks = split_repo_block(repo_name=repo_name, task_lines=bullets, limit=120000)
    return "\n\n".join(blocks).strip()


async def generate_achievement_window(*, since: str, until: str) -> dict[str, Any]:
    start_ts = time.perf_counter()

    since_dt, until_dt, err = validate_window(since=since, until=until)
    if err:
        raise ValueError(err)

    since_git = to_git_ts(since_dt)
    until_git = to_git_ts(until_dt)

    agg = await asyncio.to_thread(get_repo_achievements_in_window, since=since_git, until=until_git)
    repositories = agg.get("repositories")
    if not isinstance(repositories, list):
        repositories = []

    if not repositories:
        return {
            "ok": True,
            "since": since,
            "until": until,
            "markdown": "No development activity found in selected window.",
            "repositories": [],
        }

    period = f"{since_dt.strftime('%Y-%m-%d %H:%M')} WIB → {until_dt.strftime('%Y-%m-%d %H:%M')} WIB"
    header = f"## Daily Standup ({period})"

    for repo in repositories:
        if isinstance(repo, dict):
            _validate_repo_integrity(repo)

    client = None
    if ai_enabled():
        try:
            client = await asyncio.to_thread(load_ai_client)
        except Exception as e:
            _LOG.warning("ai_client_load_failed err=%s", str(e))
            client = None

    max_concurrency = max(1, env_int("LLM_MAX_CONCURRENCY", 3))
    llm_timeout_s = max(5, env_int("LLM_TIMEOUT_SECONDS", 30))
    llm_token_budget = max(1000, env_int("LLM_TOKEN_BUDGET", 6000))

    sem = asyncio.Semaphore(max_concurrency)

    async def _process_repo(repo: dict[str, Any]) -> dict[str, Any] | None:
        repo_name = str(repo.get("name") or "").strip()
        repo_path = str(repo.get("repo_path") or "").strip()
        commits = repo.get("detailed_commits")
        commit_count = len(commits) if isinstance(commits, list) else 0
        if not repo_name or commit_count <= 0:
            return None

        async with sem:
            if client is None:
                bullets = build_repo_task_lines_non_ai(repo)[:commit_count]
                return {
                    "repo_name": repo_name,
                    "commits_count": commit_count,
                    "bullets": bullets,
                    "markdown": _repo_markdown(repo_name=repo_name, bullets=bullets),
                    "source": "non_ai",
                }

            res = await summarize_repo_async(
                ai_client=client,
                repo_name=repo_name,
                local_path=repo_path,
                start_date=since_git,
                end_date=until_git,
                commits=commits if isinstance(commits, list) else [],
                timeout_s=llm_timeout_s,
                token_budget=llm_token_budget,
            )
            if res.ok and len(res.bullet_lines) >= commit_count:
                bullets = res.bullet_lines[:commit_count]
                return {
                    "repo_name": repo_name,
                    "commits_count": commit_count,
                    "bullets": bullets,
                    "markdown": _repo_markdown(repo_name=repo_name, bullets=bullets),
                    "source": "llm",
                }

            bullets = build_repo_task_lines_non_ai(repo)[:commit_count]
            return {
                "repo_name": repo_name,
                "commits_count": commit_count,
                "bullets": bullets,
                "markdown": _repo_markdown(repo_name=repo_name, bullets=bullets),
                "source": "non_ai_fallback",
            }

    tasks: list[asyncio.Task[dict[str, Any] | None]] = []
    for repo in repositories:
        if isinstance(repo, dict):
            tasks.append(asyncio.create_task(_process_repo(repo)))

    results = await asyncio.gather(*tasks)

    repos_out: list[dict[str, Any]] = []
    for item in results:
        if item is None:
            continue
        repos_out.append(item)

    total_dur_ms = int((time.perf_counter() - start_ts) * 1000)
    _LOG.info(
        "achievement_window_done since=%s until=%s dur_ms=%s",
        since_git,
        until_git,
        total_dur_ms,
    )

    repo_markdowns = [str(r.get("markdown") or "").strip() for r in repos_out if str(r.get("markdown") or "").strip()]
    if not repo_markdowns:
        markdown = "No development activity found in selected window."
    else:
        markdown = "\n\n".join([header, *repo_markdowns]).strip()

    return {
        "ok": True,
        "since": since,
        "until": until,
        "markdown": markdown,
        "repositories": repos_out,
    }
