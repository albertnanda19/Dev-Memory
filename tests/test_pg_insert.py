import asyncio
import os
import unittest
import uuid
from pathlib import Path


def _load_dotenv_var(name: str) -> str:
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if not env_path.exists():
        return ""
    try:
        raw = env_path.read_text(encoding="utf-8")
    except Exception:
        return ""
    for raw_line in raw.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if not line.startswith(name + "="):
            continue
        return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


class _DummyAI:
    def __init__(self, bullets: list[str]):
        self._bullets = bullets
        self.call_count = 0
        self.last_prompt = ""

    def generate_ai_summary(self, prompt: str) -> str:
        self.call_count += 1
        self.last_prompt = prompt
        return "\n".join(self._bullets)


class TestPgInsert(unittest.TestCase):
    def test_summarize_repo_async_inserts_rows(self):
        database_url = (os.getenv("DATABASE_URL") or "").strip() or _load_dotenv_var("DATABASE_URL")
        if not database_url:
            self.skipTest("DATABASE_URL not set")

        try:
            import psycopg
        except ModuleNotFoundError:
            self.skipTest("psycopg not installed")

        from ai_summarizer import summarize_repo_async

        repo_name = f"test_repo_{uuid.uuid4().hex}"
        local_path = f"/tmp/{repo_name}"

        commits = [
            {
                "hash": "a" * 40,
                "date": "2026-02-18T00:00:00Z",
                "message": "feat: one",
                "files": [{"path": "a.py"}],
            },
            {
                "hash": "b" * 40,
                "date": "2026-02-18T01:00:00Z",
                "message": "fix: two",
                "files": [{"path": "b.py"}],
            },
        ]

        dummy = _DummyAI(["- Saya one", "- Saya two"])
        res = asyncio.run(
            summarize_repo_async(
                ai_client=dummy,
                repo_name=repo_name,
                local_path=local_path,
                start_date="2026-02-18",
                end_date="2026-02-18",
                commits=commits,
                use_cache=True,
            )
        )
        self.assertTrue(res.ok)
        self.assertEqual(len(res.bullet_lines), 2)
        self.assertEqual(dummy.call_count, 1)

        with psycopg.connect(database_url) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT id FROM repositories WHERE name = %s", (repo_name,))
                repo_row = cur.fetchone()
                self.assertIsNotNone(repo_row)

                cur.execute(
                    """
                    SELECT COUNT(*)
                    FROM commits c
                    JOIN repositories r ON r.id = c.repository_id
                    WHERE r.name = %s
                    """,
                    (repo_name,),
                )
                commit_count = int((cur.fetchone() or [0])[0])
                self.assertEqual(commit_count, 2)

                cur.execute(
                    """
                    SELECT COUNT(*)
                    FROM commit_achievements ca
                    JOIN commits c ON c.id = ca.commit_id
                    JOIN repositories r ON r.id = c.repository_id
                    WHERE r.name = %s AND ca.processing_status = 'completed'
                    """,
                    (repo_name,),
                )
                ach_count = int((cur.fetchone() or [0])[0])
                self.assertEqual(ach_count, 2)

                keep = (os.getenv("KEEP_TEST_DATA") or "").strip().lower() in {"1", "true", "yes"}
                if not keep:
                    cur.execute("DELETE FROM repositories WHERE name = %s", (repo_name,))
                    conn.commit()

    def test_second_run_skips_ai_when_all_completed(self):
        database_url = (os.getenv("DATABASE_URL") or "").strip() or _load_dotenv_var("DATABASE_URL")
        if not database_url:
            self.skipTest("DATABASE_URL not set")

        try:
            import psycopg
        except ModuleNotFoundError:
            self.skipTest("psycopg not installed")

        from ai_summarizer import summarize_repo_async

        repo_name = f"test_repo_{uuid.uuid4().hex}"
        local_path = f"/tmp/{repo_name}"

        commits = [
            {
                "hash": "c" * 40,
                "date": "2026-02-18T00:00:00Z",
                "message": "feat: one",
                "files": [{"path": "a.py"}],
            },
            {
                "hash": "d" * 40,
                "date": "2026-02-18T01:00:00Z",
                "message": "fix: two",
                "files": [{"path": "b.py"}],
            },
        ]

        dummy_first = _DummyAI(["- Saya one", "- Saya two"])
        res1 = asyncio.run(
            summarize_repo_async(
                ai_client=dummy_first,
                repo_name=repo_name,
                local_path=local_path,
                start_date="2026-02-18",
                end_date="2026-02-18",
                commits=commits,
                use_cache=True,
            )
        )
        self.assertTrue(res1.ok)
        self.assertEqual(dummy_first.call_count, 1)

        dummy_second = _DummyAI(["- Saya should_not_call"])
        res2 = asyncio.run(
            summarize_repo_async(
                ai_client=dummy_second,
                repo_name=repo_name,
                local_path=local_path,
                start_date="2026-02-18",
                end_date="2026-02-18",
                commits=commits,
                use_cache=True,
            )
        )
        self.assertTrue(res2.ok)
        self.assertEqual(dummy_second.call_count, 0)

        with psycopg.connect(database_url) as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM repositories WHERE name = %s", (repo_name,))
                conn.commit()

    def test_partial_missing_only_calls_ai_for_missing(self):
        database_url = (os.getenv("DATABASE_URL") or "").strip() or _load_dotenv_var("DATABASE_URL")
        if not database_url:
            self.skipTest("DATABASE_URL not set")

        try:
            import psycopg
        except ModuleNotFoundError:
            self.skipTest("psycopg not installed")

        from ai_summarizer import summarize_repo_async

        repo_name = f"test_repo_{uuid.uuid4().hex}"
        local_path = f"/tmp/{repo_name}"

        commits = [
            {
                "hash": "e" * 40,
                "date": "2026-02-18T00:00:00Z",
                "message": "feat: one",
                "files": [{"path": "a.py"}],
            },
            {
                "hash": "f" * 40,
                "date": "2026-02-18T01:00:00Z",
                "message": "fix: two",
                "files": [{"path": "b.py"}],
            },
        ]

        dummy_seed = _DummyAI(["- Saya one", "- Saya two"])
        res1 = asyncio.run(
            summarize_repo_async(
                ai_client=dummy_seed,
                repo_name=repo_name,
                local_path=local_path,
                start_date="2026-02-18",
                end_date="2026-02-18",
                commits=commits,
                use_cache=True,
            )
        )
        self.assertTrue(res1.ok)

        with psycopg.connect(database_url) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    DELETE FROM commit_achievements ca
                    USING commits c
                    JOIN repositories r ON r.id = c.repository_id
                    WHERE ca.commit_id = c.id
                      AND r.name = %s
                      AND c.commit_hash = %s
                    """,
                    (repo_name, "f" * 40),
                )
                conn.commit()

        dummy_partial = _DummyAI(["- Saya only_missing"])
        res2 = asyncio.run(
            summarize_repo_async(
                ai_client=dummy_partial,
                repo_name=repo_name,
                local_path=local_path,
                start_date="2026-02-18",
                end_date="2026-02-18",
                commits=commits,
                use_cache=True,
            )
        )
        self.assertTrue(res2.ok)
        self.assertEqual(dummy_partial.call_count, 1)
        self.assertIn("f" * 40, dummy_partial.last_prompt)
        self.assertNotIn("e" * 40, dummy_partial.last_prompt)
        self.assertEqual(len(res2.bullet_lines), 2)

        with psycopg.connect(database_url) as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM repositories WHERE name = %s", (repo_name,))
                conn.commit()


if __name__ == "__main__":
    unittest.main()
