from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

try:
    import psycopg
    from psycopg_pool import AsyncConnectionPool

    _PSYCOPG_OK = True
except ModuleNotFoundError:
    psycopg = None  # type: ignore[assignment]
    AsyncConnectionPool = None  # type: ignore[assignment]
    _PSYCOPG_OK = False


@dataclass(frozen=True)
class AchievementRow:
    id: str
    processing_status: str
    ai_bullet: str | None


def _env(name: str) -> str:
    return (os.getenv(name) or "").strip()


def _database_url() -> str:
    return _env("DATABASE_URL")


class PgStore:
    def __init__(self, database_url: str) -> None:
        if not _PSYCOPG_OK:
            raise RuntimeError("psycopg is not installed")
        self._pool = AsyncConnectionPool(conninfo=database_url, min_size=1, max_size=10, open=False)

    async def open(self) -> None:
        if not self._pool.opened:
            await self._pool.open()

    async def close(self) -> None:
        await self._pool.close()

    async def _repo_upsert(self, *, cur: psycopg.AsyncCursor[Any], name: str, local_path: str) -> str:
        await cur.execute(
            """
            INSERT INTO repositories (name, local_path)
            VALUES (%s, %s)
            ON CONFLICT (name) DO NOTHING
            """,
            (name, local_path),
        )
        await cur.execute(
            """
            SELECT id
            FROM repositories
            WHERE name = %s
            """,
            (name,),
        )
        row = await cur.fetchone()
        if row is None:
            raise RuntimeError("repository select returned no row")
        return str(row[0])

    async def _commit_upsert(
        self,
        *,
        cur: psycopg.AsyncCursor[Any],
        repository_id: str,
        commit_hash: str,
        commit_date_iso: str,
        commit_message: str,
        raw_files: Any,
    ) -> str:
        await cur.execute(
            """
            INSERT INTO commits (repository_id, commit_hash, commit_date, commit_message, raw_files)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (repository_id, commit_hash)
            DO UPDATE SET
                commit_date = EXCLUDED.commit_date,
                commit_message = EXCLUDED.commit_message,
                raw_files = EXCLUDED.raw_files
            RETURNING id
            """,
            (repository_id, commit_hash, commit_date_iso, commit_message, raw_files),
        )
        row = await cur.fetchone()
        if row is None:
            raise RuntimeError("commit upsert returned no row")
        return str(row[0])

    async def _achievement_get(self, *, cur: psycopg.AsyncCursor[Any], commit_id: str, payload_checksum: str) -> AchievementRow | None:
        await cur.execute(
            """
            SELECT id, processing_status, ai_bullet
            FROM commit_achievements
            WHERE commit_id = %s AND payload_checksum = %s
            """,
            (commit_id, payload_checksum),
        )
        row = await cur.fetchone()
        if row is None:
            return None
        return AchievementRow(id=str(row[0]), processing_status=str(row[1] or ""), ai_bullet=row[2])

    async def _achievement_insert_pending(
        self,
        *,
        cur: psycopg.AsyncCursor[Any],
        commit_id: str,
        payload_checksum: str,
        prompt_version: str,
    ) -> str:
        await cur.execute(
            """
            INSERT INTO commit_achievements (
                commit_id,
                ai_bullet,
                model_name,
                model_version,
                token_usage,
                payload_checksum,
                prompt_version,
                processing_status,
                processed_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW())
            ON CONFLICT (commit_id, payload_checksum) DO NOTHING
            RETURNING id
            """,
            (commit_id, "", "", None, None, payload_checksum, prompt_version, "pending"),
        )
        row = await cur.fetchone()
        if row is not None:
            return str(row[0])

        existing = await self._achievement_get(cur=cur, commit_id=commit_id, payload_checksum=payload_checksum)
        if existing is None:
            raise RuntimeError("achievement pending insert failed")
        return existing.id

    async def _achievement_invalidate_others(
        self,
        *,
        cur: psycopg.AsyncCursor[Any],
        commit_id: str,
        payload_checksum: str,
    ) -> None:
        await cur.execute(
            """
            UPDATE commit_achievements
            SET processing_status = 'invalidated'
            WHERE commit_id = %s AND payload_checksum <> %s
            """,
            (commit_id, payload_checksum),
        )

    async def prepare_repo_commits(
        self,
        *,
        repository_name: str,
        local_path: str,
        commits: list[dict[str, Any]],
        payload_checksums: list[str],
        prompt_version: str,
    ) -> tuple[list[str | None], list[str]]:
        if len(commits) != len(payload_checksums):
            raise ValueError("commits and payload_checksums length mismatch")

        cached: list[str | None] = [None for _ in commits]
        achievement_ids: list[str] = ["" for _ in commits]

        await self.open()
        async with self._pool.connection() as conn:
            async with conn.transaction():
                async with conn.cursor() as cur:
                    repo_id = await self._repo_upsert(cur=cur, name=repository_name, local_path=local_path)

                    for idx, c in enumerate(commits):
                        commit_hash = str(c.get("hash") or "").strip()
                        commit_message = str(c.get("message") or "").strip()
                        commit_date_iso = str(c.get("date") or "").strip() or "1970-01-01T00:00:00Z"
                        raw_files = c.get("files")

                        if not commit_hash:
                            continue

                        commit_id = await self._commit_upsert(
                            cur=cur,
                            repository_id=repo_id,
                            commit_hash=commit_hash,
                            commit_date_iso=commit_date_iso,
                            commit_message=commit_message,
                            raw_files=raw_files,
                        )

                        checksum = payload_checksums[idx]
                        await self._achievement_invalidate_others(cur=cur, commit_id=commit_id, payload_checksum=checksum)

                        existing = await self._achievement_get(cur=cur, commit_id=commit_id, payload_checksum=checksum)
                        if existing is not None and existing.processing_status == "completed":
                            cached[idx] = (existing.ai_bullet or "").strip() or None
                            achievement_ids[idx] = existing.id
                            continue

                        if existing is not None:
                            achievement_ids[idx] = existing.id
                            continue

                        achievement_ids[idx] = await self._achievement_insert_pending(
                            cur=cur,
                            commit_id=commit_id,
                            payload_checksum=checksum,
                            prompt_version=prompt_version,
                        )

        return cached, achievement_ids

    async def mark_completed(
        self,
        *,
        achievement_id: str,
        ai_bullet: str,
        model_name: str,
        model_version: str | None,
        token_usage: int | None,
    ) -> None:
        await self.open()
        async with self._pool.connection() as conn:
            async with conn.transaction():
                async with conn.cursor() as cur:
                    await cur.execute(
                        """
                        UPDATE commit_achievements
                        SET
                            ai_bullet = %s,
                            processing_status = 'completed',
                            model_name = %s,
                            model_version = %s,
                            token_usage = %s,
                            processed_at = NOW()
                        WHERE id = %s
                        """,
                        (ai_bullet, model_name, model_version, token_usage, achievement_id),
                    )

    async def mark_failed(self, *, achievement_id: str) -> None:
        await self.open()
        async with self._pool.connection() as conn:
            async with conn.transaction():
                async with conn.cursor() as cur:
                    await cur.execute(
                        """
                        UPDATE commit_achievements
                        SET processing_status = 'failed', processed_at = NOW()
                        WHERE id = %s
                        """,
                        (achievement_id,),
                    )


_STORE: PgStore | None = None


def get_store() -> PgStore | None:
    global _STORE
    url = _database_url()
    if not url:
        return None
    if not _PSYCOPG_OK:
        return None
    if _STORE is None:
        _STORE = PgStore(url)
    return _STORE
