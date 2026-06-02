"""OpenAI-compatible provider — covers OpenAI, LM Studio, Mistral, Groq.

A single chat-completions client parameterised by base_url. The API key is read
locally (env or the git-ignored secrets file), never from the shared config.
"""
from __future__ import annotations

import requests

from prospect.config import LLMConfig
from prospect.llm.base import LLMError
from prospect.secrets import get_api_key

# Sensible default endpoints per provider when base_url is left at the Ollama default.
_DEFAULT_BASE = {
    "openai": "https://api.openai.com/v1",
    "mistral": "https://api.mistral.ai/v1",
    "groq": "https://api.groq.com/openai/v1",
    "lmstudio": "http://localhost:1234/v1",
}


class OpenAICompatProvider:
    def __init__(self, cfg: LLMConfig):
        self.cfg = cfg
        base = cfg.base_url
        if base.rstrip("/").endswith("11434") or not base:
            base = _DEFAULT_BASE.get(cfg.provider, base)
        self.base_url = base.rstrip("/")
        # LM Studio runs locally and needs no key.
        self.api_key = get_api_key(cfg.api_key_env) or ("lm-studio" if cfg.provider == "lmstudio" else None)

    def _headers(self) -> dict[str, str]:
        h = {"Content-Type": "application/json"}
        if self.api_key:
            h["Authorization"] = f"Bearer {self.api_key}"
        return h

    def complete(self, prompt: str) -> str:
        body = {
            "model": self.cfg.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": self.cfg.temperature,
        }
        if self.cfg.json_format:
            body["response_format"] = {"type": "json_object"}
        try:
            resp = requests.post(
                f"{self.base_url}/chat/completions",
                json=body,
                headers=self._headers(),
                timeout=300,
            )
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"] or ""
        except requests.RequestException as e:
            # Retry once without response_format — not every endpoint supports it.
            if self.cfg.json_format and isinstance(e, requests.HTTPError):
                body.pop("response_format", None)
                try:
                    resp = requests.post(
                        f"{self.base_url}/chat/completions",
                        json=body, headers=self._headers(), timeout=300,
                    )
                    resp.raise_for_status()
                    return resp.json()["choices"][0]["message"]["content"] or ""
                except requests.RequestException as e2:
                    raise LLMError(f"{self.cfg.provider} request failed: {e2}") from e2
            raise LLMError(f"{self.cfg.provider} request failed: {e}") from e
        except (KeyError, IndexError) as e:
            raise LLMError(f"{self.cfg.provider} returned an unexpected payload: {e}") from e

    def health(self) -> tuple[bool, str]:
        if not self.api_key and self.cfg.provider != "lmstudio":
            return False, (
                f"No API key. Set ${self.cfg.api_key_env} (env) or add it via the "
                "dashboard ⚙ panel. Keys stay local."
            )
        try:
            resp = requests.get(f"{self.base_url}/models", headers=self._headers(), timeout=10)
            resp.raise_for_status()
        except requests.RequestException as e:
            return False, f"{self.cfg.provider} unreachable at {self.base_url} ({e})"
        return True, f"{self.cfg.provider} OK ({self.cfg.model}) @ {self.base_url}"
