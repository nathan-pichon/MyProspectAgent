"""Outreacher agent — drafts a French prospecting email. It only drafts; it
never sends, and it must not invent facts or contacts (it works from the
verified summary/signals produced by the Qualifier).
"""
from __future__ import annotations

from typing import Any

from prospect.config import ProspectConfig
from prospect.engine.prompts import render_prompt
from prospect.llm.base import LLMProvider
from prospect.util import extract_json


def draft(llm: LLMProvider, cfg: ProspectConfig, evaluation: dict[str, Any]) -> dict[str, str]:
    """Return {'subject': ..., 'body': ...}. Falls back to a minimal template if
    the model returns nothing usable."""
    o = cfg.outreach
    company = evaluation.get("company", "votre entreprise")
    raw = llm.complete(render_prompt(
        "outreacher",
        sender_name=o.sender_name,
        role_title=o.role_title,
        value_proposition=cfg.offering.value_proposition,
        services=", ".join(cfg.offering.services),
        company=company,
        summary=evaluation.get("summary", ""),
        signals_found=evaluation.get("signals_found", []),
        language=o.language,
        tone=o.tone,
        max_words=o.max_words,
        call_to_action=o.call_to_action,
    ))
    data = extract_json(raw) or {}
    subject = str(data.get("subject") or "").strip()
    body = str(data.get("body") or "").strip()

    if o.signature and body and o.signature not in body:
        body = f"{body}\n\n{o.signature}"

    if not subject:
        subject = f"Échange rapide — {company}"
    if not body:
        body = (
            f"Bonjour,\n\n{cfg.offering.value_proposition}\n\n"
            f"Seriez-vous ouvert à {o.call_to_action} ?\n\n"
            f"{o.signature or o.sender_name}"
        )
    return {"subject": subject, "body": body}
