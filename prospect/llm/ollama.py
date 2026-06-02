"""Ollama provider — local, default, privacy-max. Uses the HTTP API directly
(no langchain dependency) to keep the install light."""
from __future__ import annotations

import requests

from prospect.config import LLMConfig
from prospect.llm.base import LLMError


class OllamaProvider:
    def __init__(self, cfg: LLMConfig):
        self.cfg = cfg
        self.base_url = cfg.base_url.rstrip("/")

    def complete(self, prompt: str) -> str:
        payload = {
            "model": self.cfg.model,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": self.cfg.temperature},
        }
        # Force JSON-shaped output for small models (in addition to tolerant parsing).
        if self.cfg.json_format:
            payload["format"] = "json"
        try:
            resp = requests.post(
                f"{self.base_url}/api/generate", json=payload, timeout=300
            )
            resp.raise_for_status()
            return resp.json().get("response", "")
        except requests.RequestException as e:
            raise LLMError(f"Ollama request failed: {e}") from e

    def health(self) -> tuple[bool, str]:
        try:
            resp = requests.get(f"{self.base_url}/api/tags", timeout=5)
            resp.raise_for_status()
            models = [m["name"] for m in resp.json().get("models", [])]
        except requests.RequestException as e:
            return False, (
                f"Ollama unreachable at {self.base_url} ({e}). "
                "Run `ollama serve`, or switch to an API key provider."
            )
        if not any(self.cfg.model.split(":")[0] in m for m in models):
            return False, (
                f"Model '{self.cfg.model}' not found. Pull it with "
                f"`ollama pull {self.cfg.model}`. Available: {', '.join(models) or 'none'}"
            )
        return True, f"Ollama OK ({self.cfg.model}) — {len(models)} model(s) available"
