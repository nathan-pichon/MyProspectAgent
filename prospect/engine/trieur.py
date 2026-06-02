"""Trieur agent — classifies a URL as a company/identity page vs noise.

Deterministic fast-track/reject patterns handle obvious cases (no LLM); only
ambiguous URLs reach the model.
"""
from __future__ import annotations

from prospect.engine.prompts import render_prompt
from prospect.llm.base import LLMProvider
from prospect.util import extract_json


def is_company_page(llm: LLMProvider, url: str) -> bool:
    data = extract_json(llm.complete(render_prompt("trieur", url=url))) or {}
    return bool(data.get("is_company", False))
