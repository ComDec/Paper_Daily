from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any

import requests

from paper_digest.config import LLMConfig


class LLMError(RuntimeError):
    pass


def _sha256_json(data: Any) -> str:
    payload = json.dumps(data, sort_keys=True, ensure_ascii=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _extract_json_object(text: str) -> dict[str, Any]:
    s = text.strip()
    if "```" in s:
        parts = s.split("```")
        for p in parts:
            p = p.strip()
            if p.startswith("json"):
                p = p[4:].strip()
            if p.startswith("{") and p.endswith("}"):
                return json.loads(p)

    if s.startswith("{") and s.endswith("}"):
        return json.loads(s)

    start = s.find("{")
    end = s.rfind("}")
    if start != -1 and end != -1 and end > start:
        return json.loads(s[start : end + 1])

    raise json.JSONDecodeError("No JSON object found", s, 0)


class OpenRouterClient:
    def __init__(self, cfg: LLMConfig):
        self.cfg = cfg
        self.api_key = os.getenv(cfg.api_key_env)
        if not self.api_key:
            raise LLMError(f"Missing API key env var: {cfg.api_key_env}")
        self.cache_dir = cfg.cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def chat(
        self,
        *,
        messages: list[dict[str, str]],
        max_tokens: int,
        response_format: dict[str, Any] | None = None,
    ) -> str:
        payload: dict[str, Any] = {
            "model": self.cfg.model,
            "messages": messages,
            "temperature": self.cfg.temperature,
            "max_tokens": max_tokens,
        }
        if response_format is not None:
            payload["response_format"] = response_format

        cache_key = _sha256_json({"base_url": self.cfg.base_url, **payload})
        cache_path = self.cache_dir / f"{cache_key}.json"
        if cache_path.exists():
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
            return str(cached["content"])

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        last_err: Exception | None = None
        for attempt in range(self.cfg.max_retries + 1):
            try:
                resp = requests.post(
                    self.cfg.base_url,
                    headers=headers,
                    json=payload,
                    timeout=self.cfg.timeout_s,
                )
                if resp.status_code in (429, 500, 502, 503, 504):
                    raise LLMError(
                        f"Transient error: HTTP {resp.status_code}: {resp.text[:200]}"
                    )
                resp.raise_for_status()
                data = resp.json()
                content = data["choices"][0]["message"]["content"]
                cache_path.write_text(
                    json.dumps({"content": content}, ensure_ascii=True),
                    encoding="utf-8",
                )
                return str(content)
            except Exception as e:  # noqa: BLE001
                last_err = e
                if attempt >= self.cfg.max_retries:
                    break
                time.sleep(min(2**attempt, 8))

        raise LLMError(f"OpenRouter request failed: {last_err}")

    def chat_json(
        self,
        *,
        messages: list[dict[str, str]],
        max_tokens: int,
    ) -> dict[str, Any]:
        text = self.chat(messages=messages, max_tokens=max_tokens, response_format=None)
        return _extract_json_object(text)
