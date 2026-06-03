"""Qualifier agent — scores a company against the prospecting goal with an
explainable, typed breakdown (the product's signature).

Anti-hallucination guardrail: the model must quote verbatim evidence for each
signal. We then verify *deterministically* that each quote actually appears in
the source text. Quotes that don't are dropped; if no signal evidence survives,
the Signal sub-score is capped — a 2B model cannot fabricate a buying signal.
"""
from __future__ import annotations

import re
from typing import Any

from prospect.config import ProspectConfig
from prospect.engine.prompts import render_prompt
from prospect.llm.base import LLMProvider
from prospect.util import clamp_int, extract_json

_MAXES = {"signal": 40, "need": 25, "icp": 20, "reachability": 15}
SIGNAL_CAP_WITHOUT_EVIDENCE = 10


def _load_tuning() -> str:
    """Operator tuning learned from 👎 feedback (see engine.supervisor)."""
    from pathlib import Path

    p = Path(".prospect_tuning.txt")
    return p.read_text(encoding="utf-8").strip() if p.exists() else ""


def _verdict(score: int) -> str:
    if score >= 75:
        return "strong"
    if score >= 60:
        return "good"
    if score >= 50:
        return "partial"
    return "weak"


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").lower()).strip()


def _verify_signals(raw_signals: Any, lead_text: str, source_url: str,
                    known_terms: set[str] | None = None) -> list[dict]:
    """Keep only signals whose quote actually appears in the source text.

    A quote is accepted if it is present AND either reasonably long (≥ 8 chars)
    OR it matches a known target term (e.g. "MongoDB", "Node.js"). The latter is
    essential: the most decisive signal tokens are short, so a blanket length
    cutoff would wrongly discard the exact evidence we care about.
    """
    if not isinstance(raw_signals, list):
        return []
    haystack = _norm(lead_text)
    known = known_terms or set()
    verified: list[dict] = []
    for s in raw_signals:
        if not isinstance(s, dict):
            continue
        quote = str(s.get("quote", "")).strip()
        if not quote:
            continue
        needle = _norm(quote)
        if not needle or needle not in haystack:
            continue
        if len(needle) >= 8 or needle in known or any(k in needle for k in known):
            verified.append({
                "quote": quote[:300],
                "signal": str(s.get("signal", "")).strip(),
                "source_url": source_url,
            })
    return verified


def evaluate(
    llm: LLMProvider,
    cfg: ProspectConfig,
    lead_text: str,
    *,
    contacts=None,
    source_url: str = "",
) -> dict[str, Any]:
    """Return a normalised evaluation dict. Never raises on bad model output."""
    contact_email = getattr(contacts, "email", "") if contacts else ""
    contact_email_type = getattr(contacts, "email_type", "") if contacts else ""
    contact_linkedin = getattr(contacts, "linkedin", "") if contacts else ""
    contact_website = getattr(contacts, "website", "") if contacts else ""

    raw = llm.complete(render_prompt(
        "qualifier",
        goal=cfg.goal,
        offering=cfg.offering.as_prompt_text(),
        icp=cfg.icp.as_prompt_text(),
        lead_text=lead_text[:6000],
        contact_email=contact_email,
        contact_email_type=contact_email_type,
        contact_linkedin=contact_linkedin,
        contact_website=contact_website,
        tuning=_load_tuning(),
    ))
    data = extract_json(raw) or {}

    # --- normalise breakdown ---------------------------------------------- #
    breakdown_in = data.get("breakdown") if isinstance(data.get("breakdown"), dict) else {}
    breakdown: dict[str, Any] = {}
    for key, mx in _MAXES.items():
        seg = breakdown_in.get(key, {}) if isinstance(breakdown_in.get(key), dict) else {}
        breakdown[key] = {
            "score": clamp_int(seg.get("score"), 0, mx, default=0),
            "max": mx,
            "matched": seg.get("matched", []) if isinstance(seg.get("matched"), list) else [],
            "gaps": [g for g in seg.get("gaps", []) if isinstance(g, dict)]
            if isinstance(seg.get("gaps"), list) else [],
        }

    # --- evidence-grounding guardrail (deterministic) --------------------- #
    known_terms = {
        _norm(t) for t in (cfg.icp.signals + cfg.offering.expertise) if _norm(t)
    }
    signals_found = _verify_signals(data.get("signals_found"), lead_text, source_url, known_terms)
    if not signals_found and breakdown["signal"]["score"] > SIGNAL_CAP_WITHOUT_EVIDENCE:
        # The model claimed a signal it couldn't ground — cap it and flag it.
        breakdown["signal"]["score"] = SIGNAL_CAP_WITHOUT_EVIDENCE
        breakdown["signal"]["gaps"].append(
            {"item": "Aucune preuve textuelle du signal recherché", "type": "blocking"}
        )

    # Recompute the total from (possibly capped) sub-scores — keeps it honest.
    score = sum(breakdown[k]["score"] for k in _MAXES)
    score = clamp_int(score, 0, 100, default=0)

    return {
        "score": score,
        "verdict": _verdict(score),
        "company": str(data.get("company") or "Inconnue"),
        "industry": str(data.get("industry") or ""),
        "location": str(data.get("location") or ""),
        "summary": str(data.get("summary") or ""),
        "signals_found": signals_found,
        "breakdown": breakdown,
        "signal_verified": bool(signals_found),
    }
