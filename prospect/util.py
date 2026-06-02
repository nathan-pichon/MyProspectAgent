"""Small shared utilities."""
from __future__ import annotations

import json
import re
from typing import Any

_JSON_BLOCK = re.compile(r"\{.*\}", re.DOTALL)


def extract_json(text: str) -> dict[str, Any] | None:
    """Robustly extract the first JSON object from an LLM response.

    Small local models often wrap JSON in markdown fences or add commentary.
    Returns None if nothing parseable is found.
    """
    if not text:
        return None
    # Strip common markdown fences.
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```[a-zA-Z]*\n?", "", cleaned)
        cleaned = re.sub(r"\n?```$", "", cleaned).strip()
    # Try direct parse first, then the greedy braces fallback.
    for candidate in (cleaned, None):
        if candidate is None:
            m = _JSON_BLOCK.search(cleaned)
            if not m:
                return None
            candidate = m.group(0)
        try:
            obj = json.loads(candidate)
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            continue
    return None


def clamp_int(value: Any, lo: int, hi: int, default: int = 0) -> int:
    try:
        v = int(value)
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, v))


def domain_of(url: str) -> str:
    """Return the host part of a URL (e.g. 'acme.com'), or the input unchanged."""
    if "://" in url and len(url.split("/")) > 2:
        return url.split("/")[2]
    return url
