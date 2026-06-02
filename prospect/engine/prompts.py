"""Prompt rendering — Jinja2 templates under prospect/prompts/."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

_PROMPT_DIR = Path(__file__).resolve().parent.parent / "prompts"


@lru_cache(maxsize=1)
def _env() -> Environment:
    return Environment(
        loader=FileSystemLoader(str(_PROMPT_DIR)),
        autoescape=select_autoescape(enabled_extensions=()),
        trim_blocks=True,
        lstrip_blocks=True,
    )


def render_prompt(name: str, **ctx) -> str:
    """Render prompts/<name>.md with the given context."""
    return _env().get_template(f"{name}.md").render(**ctx)
