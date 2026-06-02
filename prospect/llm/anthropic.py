"""Anthropic (Claude) provider — the recommended strong tier for the Qualifier
and Outreacher. Uses the Messages API over HTTP (no SDK dependency).

The API key is read locally (env or the git-ignored secrets file).
"""
from __future__ import annotations

import requests

from prospect.config import LLMConfig
from prospect.llm.base import LLMError
from prospect.secrets import get_api_key

_API = "https://api.anthropic.com/v1/messages"
_VERSION = "2023-06-01"


class AnthropicProvider:
    def __init__(self, cfg: LLMConfig):
        self.cfg = cfg
        self.api_key = get_api_key(cfg.api_key_env)

    def complete(self, prompt: str) -> str:
        if not self.api_key:
            raise LLMError(
                f"No Anthropic API key. Set ${self.cfg.api_key_env} or add it via the dashboard ⚙ panel."
            )
        try:
            resp = requests.post(
                _API,
                headers={
                    "x-api-key": self.api_key,
                    "anthropic-version": _VERSION,
                    "content-type": "application/json",
                },
                json={
                    "model": self.cfg.model,
                    "max_tokens": 1500,
                    "temperature": self.cfg.temperature,
                    "messages": [{"role": "user", "content": prompt}],
                },
                timeout=300,
            )
            resp.raise_for_status()
            blocks = resp.json().get("content", [])
            return "".join(b.get("text", "") for b in blocks if b.get("type") == "text")
        except requests.RequestException as e:
            raise LLMError(f"Anthropic request failed: {e}") from e

    def health(self) -> tuple[bool, str]:
        if not self.api_key:
            return False, (
                f"No Anthropic API key. Set ${self.cfg.api_key_env} (env) or add it via the "
                "dashboard ⚙ panel. Keys stay local."
            )
        return True, f"Anthropic key present ({self.cfg.model})"
