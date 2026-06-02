"""LLM provider abstraction — bring-your-own-LLM.

Default is Ollama (local). Cloud providers read their key locally (env or the
git-ignored secrets file); keys are never embedded in the shared config nor
entered on the web.

Two-tier routing: `get_provider(cfg, role)` returns a provider for the "light"
model (Scout/Trieur — high volume) or the optional "strong" model
(Qualifier/Outreacher — where quality pays off). When no strong tier is
configured, both roles resolve to the same default model.
"""
from __future__ import annotations

from typing import Literal, Protocol, runtime_checkable

from prospect.config import LLMConfig


class LLMError(Exception):
    pass


@runtime_checkable
class LLMProvider(Protocol):
    def complete(self, prompt: str) -> str:
        """Return the model's text completion for a single prompt."""
        ...

    def health(self) -> tuple[bool, str]:
        """Return (ok, message) describing connectivity."""
        ...


def _build(cfg: LLMConfig) -> LLMProvider:
    if cfg.provider == "ollama":
        from prospect.llm.ollama import OllamaProvider

        return OllamaProvider(cfg)
    if cfg.provider in ("openai", "lmstudio", "mistral", "groq"):
        from prospect.llm.openai_compat import OpenAICompatProvider

        return OpenAICompatProvider(cfg)
    if cfg.provider == "anthropic":
        from prospect.llm.anthropic import AnthropicProvider

        return AnthropicProvider(cfg)
    raise LLMError(f"Unknown LLM provider: {cfg.provider}")


def get_provider(cfg: LLMConfig, role: Literal["light", "strong"] = "light") -> LLMProvider:
    """Build a provider for a task role, applying two-tier routing."""
    return _build(cfg.for_role(role))


def check_connection(cfg: LLMConfig, role: Literal["light", "strong"] = "light") -> tuple[bool, str]:
    try:
        return get_provider(cfg, role).health()
    except Exception as e:  # noqa: BLE001
        return False, str(e)
