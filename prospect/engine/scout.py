"""Scout agent — generates the next company-finding search query (or STOP).

To avoid cold-starting a 2B model from imagination, Scout is seeded with
deterministic query templates derived from the goal + ICP signals + directories;
the LLM then varies/extends them.
"""
from __future__ import annotations

from dataclasses import dataclass
from itertools import product

from prospect.config import ProspectConfig
from prospect.engine.prompts import render_prompt
from prospect.llm.base import LLMProvider
from prospect.util import extract_json


@dataclass
class ScoutDecision:
    action: str  # "SEARCH" | "STOP"
    query: str
    thought: str = ""


def seed_queries(cfg: ProspectConfig, mode: str, limit: int = 8) -> list[str]:
    """Deterministic starter queries for a mode — proven angles the LLM varies."""
    signals = cfg.icp.signals or cfg.offering.expertise or ["MongoDB"]
    industries = cfg.icp.industries or [""]
    geos = cfg.offering.geography or [""]
    out: list[str] = []

    if mode == "WEB":
        for sig, ind, geo in product(signals, industries, geos):
            q = " ".join(p for p in (ind, f'"{sig}"', geo) if p).strip()
            if q:
                # Cut comparison/listicle noise at the query level.
                out.append(f"{q} -comparatif -alternatives -vs -avis")
    elif mode == "TECH_SIGNAL":
        # A company hiring for / publicly using the stack demonstrably USES it, and
        # the company is named on the page. ATS boards carry the company in the URL.
        # Use the raw tech terms (expertise), not the verbose ICP signal phrases —
        # job postings say "MongoDB", not "uses MongoDB".
        tech = cfg.offering.expertise or signals
        ats = ["boards.greenhouse.io", "jobs.lever.co", "jobs.ashbyhq.com", "apply.workable.com"]
        for term in tech:
            for b in ats:
                out.append(f'site:{b} "{term}"')
            out.append(f'site:welcometothejungle.com "{term}" développeur')
            out.append(f'site:linkedin.com/jobs "{term}" backend')
            out.append(f'"{term}" "we are hiring" backend engineer')
            out.append(f'"{term}" "notre stack" OR "our stack" startup')
    elif mode == "DIRECTORY":
        dirs = cfg.search.directories or ["societe.com", "pappers.fr"]
        for d, ind in product(dirs, industries or ["SaaS"]):
            out.append(f"site:{d} {ind}".strip())
    elif mode == "LINKEDIN":
        for sig, ind in product(signals, industries or [""]):
            out.append(f'site:linkedin.com/company {ind} "{sig}"'.strip())

    # De-dup, keep order.
    seen, uniq = set(), []
    for q in out:
        if q not in seen:
            seen.add(q)
            uniq.append(q)
    return uniq[:limit]


def run_scout(
    llm: LLMProvider,
    cfg: ProspectConfig,
    *,
    search_mode: str,
    recent_searches: list[str],
    visited_count: int,
    queue_count: int,
    error: str = "",
) -> ScoutDecision:
    seeds = seed_queries(cfg, search_mode)
    # Fall back to an unused seed deterministically if the LLM fails or repeats.
    unused = [q for q in seeds if q not in recent_searches]

    prompt = render_prompt(
        "scout",
        goal=cfg.goal,
        offering=cfg.offering.as_prompt_text(),
        icp=cfg.icp.as_prompt_text(),
        seeds=seeds,
        directories=", ".join(cfg.search.directories),
        recent_searches=recent_searches,
        visited_count=visited_count,
        queue_count=queue_count,
        error=error,
        search_mode=search_mode,
    )
    data = extract_json(llm.complete(prompt)) or {}
    action = str(data.get("action", "SEARCH")).upper()
    query = str(data.get("parameter", "")).strip()
    thought = str(data.get("thought", ""))

    if action == "STOP":
        # Honour STOP only when our deterministic seeds are also exhausted.
        if unused:
            return ScoutDecision(action="SEARCH", query=unused[0], thought="seed fallback (LLM stopped early)")
        return ScoutDecision(action="STOP", query="", thought=thought)

    if not query or query in recent_searches:
        if unused:
            return ScoutDecision(action="SEARCH", query=unused[0], thought="seed fallback (empty/duplicate)")
        return ScoutDecision(action="STOP", query="", thought="no fresh query available")

    return ScoutDecision(action="SEARCH", query=query, thought=thought)
