
from __future__ import annotations

from typing import Any

try:
    from pydantic import BaseModel  # type: ignore
except ModuleNotFoundError:  # pragma: no cover

    class BaseModel:  # minimal fallback (no validation)
        def __init__(self, **data: Any) -> None:
            for key, value in data.items():
                setattr(self, key, value)

        def model_dump(self) -> dict[str, Any]:
            def _dump(obj: Any) -> Any:
                if isinstance(obj, BaseModel):
                    return obj.model_dump()
                if isinstance(obj, list):
                    return [_dump(x) for x in obj]
                if isinstance(obj, dict):
                    return {k: _dump(v) for k, v in obj.items()}
                return obj

            return {k: _dump(v) for k, v in self.__dict__.items()}


class FileChange(BaseModel):
    path: str
    change_type: str


class RepoCommittedSummary(BaseModel):
    repo_name: str
    branch: str
    commits_count: int
    files_changed: int
    insertions: int
    deletions: int
    activity_type: str = "no_activity"


class RepoWorkingState(BaseModel):
    repo_name: str
    branch: str
    modified_files: list[str]
    untracked_files: list[str]
    insertions: int
    deletions: int


class DailyReport(BaseModel):
    date: str
    repos_touched: int
    committed: list[RepoCommittedSummary]
    working_state: list[RepoWorkingState]
    status: str

