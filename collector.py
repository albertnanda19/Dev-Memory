
from __future__ import annotations

import datetime as _dt
import os
import re
import subprocess
from dataclasses import dataclass

from models import DailyReport, RepoCommittedSummary, RepoWorkingState


@dataclass(frozen=True)
class _ShortStat:
    files_changed: int
    insertions: int
    deletions: int


_SHORTSTAT_RE = re.compile(
    r"(?:(?P<files>\d+)\s+files?\s+changed)?(?:,\s*)?"
    r"(?:(?P<ins>\d+)\s+insertions?\(\+\))?(?:,\s*)?"
    r"(?:(?P<del>\d+)\s+deletions?\(-\))?"
)


def _run_git(repo_path: str, args: list[str]) -> subprocess.CompletedProcess[str] | None:
    try:
        return subprocess.run(
            ["git", *args],
            cwd=repo_path,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as e:
        print(f"Error: failed running git in {repo_path}: {e}")
        return None


def _parse_shortstat(output: str) -> _ShortStat:
    if not output:
        return _ShortStat(files_changed=0, insertions=0, deletions=0)

    # Typical: " 3 files changed, 120 insertions(+), 20 deletions(-)"
    line = output.strip().splitlines()[0].strip()
    m = _SHORTSTAT_RE.search(line)
    if not m:
        return _ShortStat(files_changed=0, insertions=0, deletions=0)

    files = int(m.group("files") or 0)
    ins = int(m.group("ins") or 0)
    dele = int(m.group("del") or 0)
    return _ShortStat(files_changed=files, insertions=ins, deletions=dele)


def _repo_name(repo_path: str) -> str:
    return os.path.basename(os.path.normpath(repo_path))


def _is_git_repo(repo_path: str) -> bool:
    return os.path.isdir(repo_path) and os.path.isdir(os.path.join(repo_path, ".git"))


def _yesterday_range() -> tuple[str, str, str]:
    today = _dt.date.today()
    # Monday (0) runs a 3-day window: Fri 00:00 through Sun 23:59
    if today.weekday() == 0:
        since_day = today - _dt.timedelta(days=3)
        until_day = today - _dt.timedelta(days=1)
        date_str = until_day.strftime("%Y-%m-%d")
        since = f"{since_day.strftime('%Y-%m-%d')} 00:00"
        until = f"{until_day.strftime('%Y-%m-%d')} 23:59"
        return date_str, since, until

    yesterday = today - _dt.timedelta(days=1)
    date_str = yesterday.strftime("%Y-%m-%d")
    since = f"{date_str} 00:00"
    until = f"{date_str} 23:59"
    return date_str, since, until


def collect_daily_activity(repo_paths: list[str]) -> DailyReport:
    date_str, since, until = _yesterday_range()

    committed: list[RepoCommittedSummary] = []
    working_state: list[RepoWorkingState] = []

    for repo_path in repo_paths:
        if not repo_path or not os.path.isabs(repo_path):
            print(f"Error: invalid repo path (not absolute), skipping: {repo_path}")
            continue
        if not _is_git_repo(repo_path):
            print(f"Error: not a git repo, skipping: {repo_path}")
            continue

        repo = _repo_name(repo_path)

        branch_cp = _run_git(repo_path, ["branch", "--show-current"])
        if branch_cp is None or branch_cp.returncode != 0:
            err = (branch_cp.stderr.strip() if branch_cp else "").strip()
            print(f"Error: failed to get branch for {repo_path}: {err}")
            continue
        branch = branch_cp.stdout.strip() or "(detached)"

        # Committed activity for yesterday
        commits_cp = _run_git(
            repo_path,
            [
                "log",
                f"--since={since}",
                f"--until={until}",
                "--no-merges",
                "--pretty=format:%H|%s",
            ],
        )
        commits_count = 0
        commit_hashes: list[str] = []
        commit_messages: list[str] = []
        commit_details: list[dict[str, object]] = []
        if commits_cp is not None and commits_cp.returncode == 0:
            for raw in commits_cp.stdout.splitlines():
                line = raw.strip()
                if not line:
                    continue
                if "|" not in line:
                    continue
                commit_hash, message = line.split("|", 1)
                commit_hash = commit_hash.strip()
                message = message.strip()
                if not commit_hash or not message:
                    continue
                commit_hashes.append(commit_hash)
                commit_messages.append(message)

            commits_count = len(commit_hashes)
        elif commits_cp is not None:
            print(
                f"Error: failed to read commits for {repo_path}: {commits_cp.stderr.strip()}"
            )

        files_changed = 0
        committed_ins = 0
        committed_del = 0
        if commits_count > 0:
            for commit_hash, msg in zip(commit_hashes, commit_messages, strict=False):
                show_cp = _run_git(
                    repo_path,
                    [
                        "show",
                        "--shortstat",
                        "--pretty=format:",
                        commit_hash,
                    ],
                )
                if show_cp is None:
                    continue
                if show_cp.returncode != 0:
                    print(
                        f"Error: failed to read commit shortstat for {repo_path}: {show_cp.stderr.strip()}"
                    )
                    continue
                for line in show_cp.stdout.splitlines():
                    st = _parse_shortstat(line)
                    files_changed += st.files_changed
                    committed_ins += st.insertions
                    committed_del += st.deletions

                files_cp = _run_git(
                    repo_path,
                    [
                        "show",
                        "--name-only",
                        "--pretty=format:",
                        commit_hash,
                    ],
                )
                files: list[str] = []
                if files_cp is not None and files_cp.returncode == 0:
                    for ln in files_cp.stdout.splitlines():
                        p = ln.strip()
                        if p:
                            files.append(p)
                elif files_cp is not None:
                    print(
                        f"Error: failed to read commit files for {repo_path}: {files_cp.stderr.strip()}"
                    )

                commit_details.append(
                    {
                        "hash": commit_hash,
                        "message": msg,
                        "files": files,
                    }
                )

            committed.append(
                RepoCommittedSummary(
                    repo_name=repo,
                    branch=branch,
                    commits_count=commits_count,
                    files_changed=files_changed,
                    insertions=committed_ins,
                    deletions=committed_del,
                    commit_messages=commit_messages,
                    commit_details=commit_details,
                )
            )

        # Working state
        status_cp = _run_git(repo_path, ["status", "--porcelain"])
        modified_files: list[str] = []
        untracked_files: list[str] = []
        if status_cp is not None and status_cp.returncode == 0:
            for raw in status_cp.stdout.splitlines():
                line = raw.rstrip("\n")
                if line.startswith("??"):
                    untracked_files.append(line[3:].strip())
                    continue
                # ' M file', 'M  file', 'MM file', etc.
                if len(line) >= 3 and (line[0] == "M" or line[1] == "M"):
                    modified_files.append(line[3:].strip())
        elif status_cp is not None:
            print(
                f"Error: failed to read working state for {repo_path}: {status_cp.stderr.strip()}"
            )

        wd_ins = 0
        wd_del = 0
        diff_cp = _run_git(repo_path, ["diff", "--shortstat"])
        if diff_cp is not None and diff_cp.returncode == 0:
            st = _parse_shortstat(diff_cp.stdout)
            wd_ins += st.insertions
            wd_del += st.deletions
        elif diff_cp is not None:
            print(
                f"Error: failed to read git diff shortstat for {repo_path}: {diff_cp.stderr.strip()}"
            )

        cached_cp = _run_git(repo_path, ["diff", "--cached", "--shortstat"])
        if cached_cp is not None and cached_cp.returncode == 0:
            st = _parse_shortstat(cached_cp.stdout)
            wd_ins += st.insertions
            wd_del += st.deletions
        elif cached_cp is not None:
            print(
                f"Error: failed to read git diff --cached shortstat for {repo_path}: {cached_cp.stderr.strip()}"
            )

        working_state.append(
            RepoWorkingState(
                repo_name=repo,
                branch=branch,
                modified_files=sorted(set(modified_files)),
                untracked_files=sorted(set(untracked_files)),
                insertions=wd_ins,
                deletions=wd_del,
            )
        )

    filtered_working_state = [
        w for w in working_state if w.modified_files or w.untracked_files or w.insertions or w.deletions
    ]
    committed_repo_names = {c.repo_name for c in committed}
    working_repo_names = {w.repo_name for w in filtered_working_state}
    repos_touched = len(committed_repo_names | working_repo_names)

    status = "success" if repos_touched > 0 else "no_activity"

    return DailyReport(
        date=date_str,
        repos_touched=repos_touched,
        committed=committed if repos_touched > 0 else [],
        working_state=filtered_working_state if repos_touched > 0 else [],
        status=status,
    )

