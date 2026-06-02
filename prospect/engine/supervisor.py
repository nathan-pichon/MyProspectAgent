"""Supervisor — opt-in prompt tuning from 👎 feedback.

Looks at the prospects the user thumbed down, asks the (strong) LLM for a short
list of criteria adjustments, and saves them to a local tuning file that the
Qualifier injects on its next runs. Fully local, fully optional.
"""
from __future__ import annotations

import json
from pathlib import Path

from prospect.config import ProspectConfig
from prospect.engine.prompts import render_prompt  # noqa: F401  (kept for parity)
from prospect.llm.base import get_provider
from prospect.store import Store
from prospect.util import extract_json

TUNING_FILE = ".prospect_tuning.txt"


def load_tuning() -> str:
    p = Path(TUNING_FILE)
    return p.read_text(encoding="utf-8").strip() if p.exists() else ""


def save_tuning(text: str) -> None:
    Path(TUNING_FILE).write_text(text.strip() + "\n", encoding="utf-8")


def suggest(cfg: ProspectConfig, store: Store) -> str:
    """Return a short tuning addendum derived from down-voted prospects, or ''."""
    rows = store.conn.execute(
        "SELECT company, industry, summary, score FROM prospects WHERE feedback = -1 ORDER BY last_seen DESC LIMIT 15"
    ).fetchall()
    if not rows:
        return ""
    examples = "\n".join(
        f"- {r['company']} ({r['industry']}, score {r['score']}): {r['summary']}" for r in rows
    )
    prompt = (
        "You tune a B2B prospect-qualification rubric. The user REJECTED these prospects "
        "(thumbs-down) — they are false positives. Infer 2-4 concise, general rules that would "
        "have scored them lower, WITHOUT hurting genuine matches. Keep rules short and actionable.\n\n"
        f"PROSPECTING GOAL: {cfg.goal}\n\nREJECTED PROSPECTS:\n{examples}\n\n"
        'Return ONLY raw JSON: {"rules": ["...", "..."]}'
    )
    data = extract_json(get_provider(cfg.llm, "strong").complete(prompt)) or {}
    rules = [str(r).strip() for r in data.get("rules", []) if str(r).strip()]
    if not rules:
        return ""
    return "\n".join(f"- {r}" for r in rules)
