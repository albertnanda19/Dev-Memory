import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from discord_delivery.discord_client import send_message_or_file
from discord_delivery.send_report import send_daily_standup


class _Resp:
    def __init__(self, status: int, body: bytes, headers: dict[str, str] | None = None):
        self.status = status
        self._body = body
        self.headers = headers or {}

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class TestDiscordDelivery(unittest.TestCase):
    def test_missing_credentials_returns_failure(self):
        with patch.dict(os.environ, {}, clear=True), patch(
            "discord_delivery.discord_client._DOTENV", {}
        ):
            res = send_message_or_file(
                content="x",
                file_path=None,
                filename=None,
                mention_user_id=None,
                retry_once=True,
            )
            self.assertFalse(res.ok)
            self.assertEqual(res.error, "missing_credentials")

    def test_rate_limit_429_retries_then_success(self):
        bodies = [
            _Resp(429, json.dumps({"retry_after": 0.01}).encode("utf-8")),
            _Resp(200, b"{}"),
        ]

        def _fake_urlopen(req, timeout=30):
            return bodies.pop(0)

        with patch.dict(
            os.environ,
            {"DISCORD_BOT_TOKEN": "t", "DISCORD_CHANNEL_ID": "c"},
            clear=True,
        ), patch("discord_delivery.discord_client.urlopen", side_effect=_fake_urlopen), patch(
            "discord_delivery.discord_client.time.sleep"
        ) as sleep_mock:
            res = send_message_or_file(
                content="x",
                file_path=None,
                filename=None,
                mention_user_id=None,
                retry_once=True,
            )
            self.assertTrue(res.ok)
            self.assertEqual(res.retry_count, 1)
            sleep_mock.assert_called()

    def test_non_2xx_retries_once_then_fails(self):
        bodies = [
            _Resp(500, b"oops"),
            _Resp(500, b"oops"),
        ]

        def _fake_urlopen(req, timeout=30):
            return bodies.pop(0)

        with patch.dict(
            os.environ,
            {"DISCORD_BOT_TOKEN": "t", "DISCORD_CHANNEL_ID": "c"},
            clear=True,
        ), patch("discord_delivery.discord_client.urlopen", side_effect=_fake_urlopen), patch(
            "discord_delivery.discord_client.time.sleep"
        ) as sleep_mock:
            res = send_message_or_file(
                content="x",
                file_path=None,
                filename=None,
                mention_user_id=None,
                retry_once=True,
            )
            self.assertFalse(res.ok)
            self.assertEqual(res.status_code, 500)
            self.assertEqual(res.retry_count, 1)
            sleep_mock.assert_called_with(5)

    def test_empty_markdown_file_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            md_path = Path(td) / "x.md"
            md_path.write_text("", encoding="utf-8")
            json_path = Path(td) / "x.json"
            json_path.write_text("{}\n", encoding="utf-8")

            res = send_daily_standup(
                date_str="2026-02-12",
                markdown_path=md_path,
                daily_json_path=json_path,
            )
            self.assertFalse(res.ok)
            self.assertEqual(res.error, "markdown_empty")


if __name__ == "__main__":
    unittest.main()
