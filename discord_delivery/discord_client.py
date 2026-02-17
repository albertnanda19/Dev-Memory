from __future__ import annotations

import json
import logging
import mimetypes
import os
import time
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


_LOGGER_NAME = "dev-memory-discord"


class _IsoFormatter(logging.Formatter):
    def formatTime(self, record: logging.LogRecord, datefmt: str | None = None) -> str:
        dt = datetime.fromtimestamp(record.created)
        return dt.isoformat(timespec="seconds")


def get_discord_logger() -> logging.Logger:
    logger = logging.getLogger(_LOGGER_NAME)
    if getattr(logger, "_dev_memory_configured", False):
        return logger

    logger.setLevel(logging.INFO)
    logger.propagate = False

    logs_dir = Path(__file__).resolve().parent.parent / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_path = logs_dir / "discord.log"

    handler = logging.FileHandler(log_path, encoding="utf-8")
    handler.setLevel(logging.INFO)
    handler.setFormatter(
        _IsoFormatter("[%(asctime)s] [%(levelname)s] [%(module)s] %(message)s")
    )
    logger.addHandler(handler)

    logger._dev_memory_configured = True  # type: ignore[attr-defined]
    return logger


_LOG = get_discord_logger()


@dataclass(frozen=True)
class DiscordResult:
    ok: bool
    status_code: int | None
    latency_ms: int | None
    error: str | None
    retry_count: int


def _env(name: str) -> str:
    return (os.getenv(name) or "").strip()


def _load_dotenv_vars() -> dict[str, str]:
    # Load from project root .env (same folder level as main.py)
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if not env_path.exists():
        return {}

    try:
        content = env_path.read_text(encoding="utf-8")
    except Exception:
        return {}

    out: dict[str, str] = {}
    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
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


def _env_any(name: str) -> str:
    # Prefer real environment; fallback to .env file.
    v = _env(name)
    if v:
        return v
    return (_DOTENV.get(name) or "").strip()


def _request(
    *,
    token: str,
    url: str,
    method: str,
    headers: dict[str, str],
    body: bytes | None,
    timeout: int = 30,
) -> tuple[int, bytes, dict[str, str]]:
    req = Request(url, data=body, headers=headers, method=method)
    try:
        with urlopen(req, timeout=timeout) as resp:
            raw = resp.read() or b""
            status = int(getattr(resp, "status", 200) or 200)
            resp_headers = {k.lower(): v for k, v in (resp.headers.items() if resp.headers else [])}
            return status, raw, resp_headers
    except HTTPError as e:
        raw = b""
        try:
            raw = e.read() or b""
        except Exception:
            raw = b""
        status = int(getattr(e, "code", 0) or 0)
        hdrs = {k.lower(): v for k, v in (e.headers.items() if e.headers else [])}
        return status, raw, hdrs
    except URLError as e:
        raise RuntimeError(f"Discord request failed: {e}") from e


def _json_request(
    *, token: str, url: str, payload: dict[str, Any]
) -> tuple[int, bytes, dict[str, str]]:
    body = json.dumps(payload).encode("utf-8")
    headers = {
        "Authorization": f"Bot {token}",
        "Content-Type": "application/json",
        "User-Agent": "dev-memory/1.0",
    }
    return _request(token=token, url=url, method="POST", headers=headers, body=body)


def _apply_allowed_mentions(payload: dict[str, Any], mention_user_id: str | None) -> dict[str, Any]:
    if not mention_user_id:
        return payload
    out = dict(payload)
    out["allowed_mentions"] = {"parse": [], "users": [mention_user_id]}
    return out


def _multipart_request(
    *, token: str, url: str, payload_json: dict[str, Any], filename: str, file_bytes: bytes
) -> tuple[int, bytes, dict[str, str]]:
    boundary = "----devmemory-" + uuid.uuid4().hex

    file_ct = mimetypes.guess_type(filename)[0] or "text/markdown"

    parts: list[bytes] = []
    parts.append(
        (
            f"--{boundary}\r\n"
            "Content-Disposition: form-data; name=\"payload_json\"\r\n"
            "Content-Type: application/json\r\n\r\n"
        ).encode("utf-8")
        + json.dumps(payload_json).encode("utf-8")
        + b"\r\n"
    )

    parts.append(
        (
            f"--{boundary}\r\n"
            f"Content-Disposition: form-data; name=\"files[0]\"; filename=\"{filename}\"\r\n"
            f"Content-Type: {file_ct}\r\n\r\n"
        ).encode("utf-8")
        + file_bytes
        + b"\r\n"
    )

    parts.append(f"--{boundary}--\r\n".encode("utf-8"))
    body = b"".join(parts)

    headers = {
        "Authorization": f"Bot {token}",
        "Content-Type": f"multipart/form-data; boundary={boundary}",
        "User-Agent": "dev-memory/1.0",
    }
    return _request(token=token, url=url, method="POST", headers=headers, body=body)


def send_message_or_file(
    *,
    content: str,
    file_path: Path | None,
    filename: str | None,
    mention_user_id: str | None,
    retry_once: bool = True,
) -> DiscordResult:
    token = _env_any("DISCORD_BOT_TOKEN")
    channel_id = _env_any("DISCORD_CHANNEL_ID")

    if not token or not channel_id:
        _LOG.warning("Discord credentials missing (DISCORD_BOT_TOKEN/DISCORD_CHANNEL_ID)")
        return DiscordResult(
            ok=False,
            status_code=None,
            latency_ms=None,
            error="missing_credentials",
            retry_count=0,
        )

    url = f"https://discord.com/api/v10/channels/{channel_id}/messages"

    if mention_user_id:
        content = f"<@{mention_user_id}>\n" + content

    attempt = 0
    retry_count = 0
    last_err: str | None = None
    last_status: int | None = None
    last_latency: int | None = None

    while True:
        attempt += 1
        t0 = time.perf_counter()
        try:
            if file_path is not None:
                file_bytes = file_path.read_bytes()
                payload = _apply_allowed_mentions({"content": content}, mention_user_id)
                status, raw, hdrs = _multipart_request(
                    token=token,
                    url=url,
                    payload_json=payload,
                    filename=filename or file_path.name,
                    file_bytes=file_bytes,
                )
            else:
                payload = _apply_allowed_mentions({"content": content}, mention_user_id)
                status, raw, hdrs = _json_request(token=token, url=url, payload=payload)

            latency_ms = int((time.perf_counter() - t0) * 1000)
            last_latency = latency_ms
            last_status = status

            if status == 429:
                retry_after = 5.0
                try:
                    data = json.loads((raw or b"{}").decode("utf-8"))
                    ra = data.get("retry_after")
                    if isinstance(ra, (int, float)) and ra > 0:
                        retry_after = float(ra)
                except Exception:
                    retry_after = 5.0

                _LOG.warning(
                    "Discord rate limited (429). retry_after=%.2fs attempt=%s",
                    retry_after,
                    attempt,
                )

                if retry_once and retry_count < 1:
                    retry_count += 1
                    time.sleep(retry_after)
                    continue
                last_err = "rate_limited"
                break

            if 200 <= status < 300:
                _LOG.info(
                    "Discord send success (status=%s latency_ms=%s retry=%s)",
                    status,
                    latency_ms,
                    retry_count,
                )
                return DiscordResult(
                    ok=True,
                    status_code=status,
                    latency_ms=latency_ms,
                    error=None,
                    retry_count=retry_count,
                )

            # Non-2xx
            body_preview = (raw or b"")[:500].decode("utf-8", errors="replace")
            last_err = body_preview or f"http_{status}"
            _LOG.error(
                "Discord send failed (status=%s latency_ms=%s retry=%s body=%s)",
                status,
                latency_ms,
                retry_count,
                body_preview,
            )

            if retry_once and retry_count < 1:
                retry_count += 1
                time.sleep(5)
                continue

            break

        except Exception as e:
            latency_ms = int((time.perf_counter() - t0) * 1000)
            last_latency = latency_ms
            last_err = str(e)
            _LOG.exception(
                "Discord send exception (latency_ms=%s retry=%s): %s",
                latency_ms,
                retry_count,
                e,
            )

            if retry_once and retry_count < 1:
                retry_count += 1
                time.sleep(5)
                continue
            break

    return DiscordResult(
        ok=False,
        status_code=last_status,
        latency_ms=last_latency,
        error=last_err,
        retry_count=retry_count,
    )
