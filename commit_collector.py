from __future__ import annotations

import datetime as _dt
import os
import subprocess
from dataclasses import dataclass
from typing import Any

from logger import get_logger


_LOG = get_logger()


@dataclass(frozen=True)
class CommitFile:
    path: str


@dataclass(frozen=True)
class RawCommit:
    commit_hash: str
    message: str
    files: list[CommitFile]


@dataclass(frozen=True)
class RepoRawCommits:
    repository: str
    repo_path: str
    commit_count_expected: int
    commits: list[RawCommit]


def _repo_name(repo_path: str) -> str:
    return os.path.basename(os.path.normpath(repo_path))


def _run_git(repo_path: str, args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=repo_path,
        capture_output=True,
        text=True,
        check=False,
    )


def _parse_date_range(*, start_date: str, end_date: str) -> tuple[str, str]:
    start = _dt.datetime.strptime(start_date, "%Y-%m-%d").date()
    end = _dt.datetime.strptime(end_date, "%Y-%m-%d").date()
    since = f"{start.isoformat()} 00:00"
    until = f"{end.isoformat()} 23:59"
    return since, until


def _expected_commit_count(repo_path: str, since: str, until: str) -> int:
    cp = _run_git(repo_path, ["rev-list", "--count", f"--since={since}", f"--until={until}", "HEAD"])
    if cp.returncode != 0:
        err = (cp.stderr or cp.stdout).strip()
        raise RuntimeError(f"git rev-list failed ({_repo_name(repo_path)}): {err}")
    try:
        return int((cp.stdout or "0").strip() or 0)
    except Exception:
        return 0


def _parse_log_output(raw: str) -> list[RawCommit]:
    commits: list[RawCommit] = []

    current_hash = ""
    current_msg = ""
    current_files: list[CommitFile] = []

    def _flush():
        nonlocal current_hash, current_msg, current_files
        if not current_hash:
            return
        commits.append(
            RawCommit(
                commit_hash=current_hash,
                message=current_msg,
                files=list(current_files),
            )
        )
        current_hash = ""
        current_msg = ""
        current_files = []

    for raw_line in (raw or "").splitlines():
        line = raw_line.rstrip("\n")
        if not line.strip():
            continue

        if "|" in line:
            parts = line.split("|", 1)
            if len(parts) == 2:
                commit_hash = parts[0].strip()
                message = parts[1].strip()
                if commit_hash:
                    _flush()
                    current_hash = commit_hash
                    current_msg = message
                    continue

        path = line.strip()
        if path:
            current_files.append(CommitFile(path=path))

    _flush()
    return commits


def collect_repo_commits(*, repo_path: str, start_date: str, end_date: str) -> RepoRawCommits:
    if not repo_path or not os.path.isabs(repo_path):
        raise ValueError("repo_path must be an absolute path")

    since, until = _parse_date_range(start_date=start_date, end_date=end_date)

    expected = _expected_commit_count(repo_path, since, until)

    cp = _run_git(
        repo_path,
        [
            "log",
            f"--since={since}",
            f"--until={until}",
            '--pretty=format:%H|%s',
            "--name-only",
        ],
    )

    if cp.returncode != 0:
        err = (cp.stderr or cp.stdout).strip()
        raise RuntimeError(f"git log failed ({_repo_name(repo_path)}): {err}")

    commits = _parse_log_output(cp.stdout)

    repo = _repo_name(repo_path)
    if expected != len(commits):
        _LOG.error(
            "commit_collector mismatch repo=%s expected=%s parsed=%s",
            repo,
            expected,
            len(commits),
        )
        raise RuntimeError(f"commit mismatch for {repo}: expected={expected} parsed={len(commits)}")

    return RepoRawCommits(
        repository=repo,
        repo_path=repo_path,
        commit_count_expected=expected,
        commits=commits,
    )


def collect_commits_for_repos(*, repo_paths: list[str], start_date: str, end_date: str) -> list[RepoRawCommits]:
    out: list[RepoRawCommits] = []
    for repo_path in repo_paths:
        data = collect_repo_commits(repo_path=repo_path, start_date=start_date, end_date=end_date)
        out.append(data)
    return out
