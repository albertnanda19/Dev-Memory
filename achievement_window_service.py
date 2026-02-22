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


async def generate_achievement_window_markdown(*, since: str, until: str) -> str:
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
        return "No development activity found in selected window."

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

    async def _process_repo(repo: dict[str, Any]) -> tuple[str, int, int, list[str]] | None:
        repo_name = str(repo.get("name") or "").strip()
        repo_path = str(repo.get("repo_path") or "").strip()
        commits = repo.get("detailed_commits")
        commit_count = len(commits) if isinstance(commits, list) else 0
        if not repo_name or commit_count <= 0:
            return None

        async with sem:
            if client is None:
                task_lines = build_repo_task_lines_non_ai(repo)
                return repo_name, commit_count, len(task_lines), task_lines

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
            if not res.ok:
                return None
            task_lines = res.bullet_lines
            return repo_name, commit_count, len(task_lines), task_lines

    tasks: list[asyncio.Task[tuple[str, int, int, list[str]] | None]] = []
    for repo in repositories:
        if isinstance(repo, dict):
            tasks.append(asyncio.create_task(_process_repo(repo)))

    results = await asyncio.gather(*tasks)

    repo_blocks: list[str] = []
    total_commits_collected = 0
    total_bullet_points_generated = 0

    for item in results:
        if item is None:
            continue
        repo_name, commit_count, bullet_count, task_lines = item
        if bullet_count < commit_count:
            _LOG.error(
                "achievement_task_coverage_mismatch repo=%s commits=%s bullets=%s",
                repo_name,
                commit_count,
                bullet_count,
            )
            continue

        total_commits_collected += commit_count
        total_bullet_points_generated += commit_count

        blocks = split_repo_block(repo_name=repo_name, task_lines=task_lines[:commit_count], limit=120000)
        if blocks:
            repo_blocks.append("\n\n".join(blocks))

    if total_commits_collected != total_bullet_points_generated:
        _LOG.error(
            "achievement_total_coverage_mismatch commits=%s bullets=%s since=%s until=%s",
            total_commits_collected,
            total_bullet_points_generated,
            since_git,
            until_git,
        )
        raise RuntimeError(
            f"total task coverage mismatch commits={total_commits_collected} bullets={total_bullet_points_generated}"
        )

    total_dur_ms = int((time.perf_counter() - start_ts) * 1000)
    _LOG.info(
        "achievement_window_done since=%s until=%s dur_ms=%s",
        since_git,
        until_git,
        total_dur_ms,
    )

    return "\n\n".join([header, *repo_blocks]).strip()
