
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from logger import get_logger


_LOG = get_logger()


def _load_dotenv_vars() -> dict[str, str]:
    env_path = Path(__file__).resolve().parent / ".env"
    if not env_path.exists():
        return {}

    content = env_path.read_text(encoding="utf-8")
    out: dict[str, str] = {}
    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            out[key] = value
    return out


def _get_config() -> dict[str, str]:
    file_env = _load_dotenv_vars()

    def _get(name: str) -> str:
        return os.environ.get(name) or file_env.get(name, "")

    return {
        "api_url": _get("LLM_API_URL"),
        "api_key": _get("LLM_API_KEY"),
        "model": _get("LLM_MODEL"),
        "gemini_api_key": _get("GEMINI_API_KEY"),
        "gemini_model": _get("GEMINI_MODEL"),
    }


def _request_json(
    *, url: str, headers: dict[str, str], payload: dict[str, Any]
) -> tuple[dict[str, Any], int, int]:
    req = Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )

    try:
        with urlopen(req, timeout=30) as resp:
            raw_bytes = resp.read()
            status_code = int(getattr(resp, "status", 200) or 200)
            raw = raw_bytes.decode("utf-8")
    except HTTPError as e:
        detail = ""
        try:
            detail = e.read().decode("utf-8")
        except Exception:
            detail = ""
        _LOG.exception("LLM request failed (HTTP %s): %s", getattr(e, "code", "?"), detail)
        raise RuntimeError(f"LLM request failed (HTTP {e.code}): {detail}".strip()) from e
    except URLError as e:
        _LOG.exception("LLM request failed: %s", e)
        raise RuntimeError(f"LLM request failed: {e}") from e

    return json.loads(raw or "{}"), status_code, len(raw)


def _generate_via_generic_chat(*, prompt: str, api_url: str, api_key: str, model: str) -> str:
    payload: dict[str, Any] = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0,
    }

    t0 = time.perf_counter()
    data, status_code, response_size = _request_json(
        url=api_url,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        payload=payload,
    )
    latency = time.perf_counter() - t0
    _LOG.info(
        "AI request completed (provider=generic, status=%s, prompt_chars=%s, response_chars=%s, latency=%.2fs)",
        status_code,
        len(prompt or ""),
        response_size,
        latency,
    )

    choices = data.get("choices")
    if isinstance(choices, list) and choices:
        msg = choices[0].get("message") or {}
        content = msg.get("content")
        if isinstance(content, str):
            return content.strip()

        text = choices[0].get("text")
        if isinstance(text, str):
            return text.strip()

    if isinstance(data.get("output"), str):
        return str(data["output"]).strip()
    if isinstance(data.get("text"), str):
        return str(data["text"]).strip()

    raise RuntimeError("LLM response did not contain a recognized text field")


def _generate_via_gemini(*, prompt: str, api_key: str, model: str) -> str:
    # REST API (no external dependencies)
    # https://ai.google.dev/api/generate-content
    base = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    url = base + "?" + urlencode({"key": api_key})

    payload: dict[str, Any] = {
        "contents": [
            {
                "parts": [
                    {
                        "text": prompt,
                    }
                ]
            }
        ]
    }

    t0 = time.perf_counter()
    data, status_code, response_size = _request_json(
        url=url,
        headers={
            "Content-Type": "application/json",
        },
        payload=payload,
    )
    latency = time.perf_counter() - t0
    _LOG.info(
        "AI request completed (provider=gemini, model=%s, status=%s, prompt_chars=%s, response_chars=%s, latency=%.2fs)",
        model,
        status_code,
        len(prompt or ""),
        response_size,
        latency,
    )

    candidates = data.get("candidates")
    if isinstance(candidates, list) and candidates:
        content = candidates[0].get("content") or {}
        parts = content.get("parts")
        if isinstance(parts, list) and parts:
            text = parts[0].get("text")
            if isinstance(text, str):
                return text.strip()

    raise RuntimeError("Gemini response did not contain candidates/content/parts text")


def generate_ai_summary(prompt: str) -> str:
    config = _get_config()
    api_url = config["api_url"].strip()
    api_key = config["api_key"].strip()
    model = (config["model"] or "gpt-4o-mini").strip()

    gemini_api_key = config["gemini_api_key"].strip()
    gemini_model = (config["gemini_model"] or "gemini-3-flash-preview").strip()

    if api_url:
        if not api_key:
            _LOG.warning("LLM_API_KEY missing")
            raise RuntimeError("LLM_API_KEY missing")
        return _generate_via_generic_chat(
            prompt=prompt,
            api_url=api_url,
            api_key=api_key,
            model=model,
        )

    if gemini_api_key:
        return _generate_via_gemini(prompt=prompt, api_key=gemini_api_key, model=gemini_model)

    _LOG.warning("No LLM credentials found (set GEMINI_API_KEY or LLM_API_URL/LLM_API_KEY)")
    raise RuntimeError("No LLM credentials found (set GEMINI_API_KEY or LLM_API_URL/LLM_API_KEY)")
