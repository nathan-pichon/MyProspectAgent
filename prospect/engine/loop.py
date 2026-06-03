"""Orchestration loop.

Two phases per step:
 1. Fast-path — if the URL queue is non-empty, pop & process one URL
    (filters → Trieur fast-track/LLM → scrape → contacts → Qualifier → Outreacher).
 2. Scout phase — if the queue is empty, ask the Scout for the next query, fan
    out to the active sources, score text-carrying leads directly and queue the rest.

Scrapers/filters are imported lazily so `validate`/`doctor` work without the
optional `scrape` extra installed. Two-tier LLM routing: Scout/Trieur use the
light model; Qualifier/Outreacher use the strong tier when configured.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

from rich.console import Console

from prospect.config import ProspectConfig
from prospect.engine import contacts as contacts_mod
from prospect.engine import outreacher, qualifier, scout, trieur
from prospect.llm.base import get_provider
from prospect.sources import Lead
from prospect.store import Prospect, Store
from prospect.util import domain_of

console = Console()


@dataclass
class RunStats:
    steps: int = 0
    searches: int = 0
    urls_seen: int = 0
    matches: int = 0
    new_matches: list[dict] = field(default_factory=list)
    phase: str = "starting"
    last_match: dict | None = None


def _evaluate_lead(lead, page, llm_strong, cfg, store, stats, threshold) -> None:
    """Score one lead's text, and on a match extract contacts + draft outreach."""
    url = lead.url
    text = page.text if page else lead.text
    if not text or len(text.strip()) < 100:
        store.record_rejection(url, "empty", "page vide ou trop courte")
        return

    links = page.links if page else []
    anchors = page.anchors if page else []
    contacts = contacts_mod.extract(text, links, url)

    # Aggregator/ATS leads (e.g. Welcome to the Jungle) rarely expose an email on
    # the listing — follow the company's own site ("Voir le site") to find one,
    # before scoring so Reachability reflects it.
    if anchors and contacts_mod.needs_enrichment(url, contacts):
        from prospect.engine import scrapers as _scrapers

        def _fetch(u):
            try:
                return _scrapers.extract(u)
            except Exception:  # noqa: BLE001
                return None

        before = contacts.email
        contacts = contacts_mod.enrich_from_website(contacts, anchors, url, _fetch)
        if contacts.email and not before:
            console.print(f"  [dim]↳ contact enrichi via {domain_of(contacts.website or url)}: {contacts.email}[/]")

    evaluation = qualifier.evaluate(llm_strong, cfg, text, contacts=contacts, source_url=url)

    if evaluation["score"] >= threshold:
        outreach = outreacher.draft(llm_strong, cfg, evaluation)
        from prospect.engine import filters as _filters

        company = evaluation["company"]
        if company in ("", "Inconnue"):
            company = lead.company or _filters.company_from_ats_url(url) or domain_of(url)
        prospect = Prospect(
            url=url,
            company=company,
            website=contacts.website or (f"https://{domain_of(url)}" if "://" in url else ""),
            email=contacts.email,
            email_type=contacts.email_type,
            linkedin=contacts.linkedin,
            location=evaluation["location"],
            industry=evaluation["industry"],
            score=evaluation["score"],
            breakdown=evaluation["breakdown"],
            summary=evaluation["summary"],
            signals_found=evaluation["signals_found"],
            outreach_subject=outreach["subject"],
            outreach_body=outreach["body"],
            source=lead.source or domain_of(url),
        )
        is_new = store.upsert_prospect(prospect)
        stats.matches += 1
        if is_new:
            stats.new_matches.append(evaluation)
            stats.last_match = {
                "company": prospect.company, "score": prospect.score,
                "email": prospect.email, "source": prospect.source,
            }
            contact_str = prospect.email or prospect.linkedin or "pas de contact"
            console.print(
                f"  [green]✦ Prospect[/] {prospect.company} "
                f"· [bold]{evaluation['score']}/100[/] · {contact_str} [dim]({prospect.source})[/]"
            )
    else:
        reason, detail = _rejection_reason(evaluation, threshold)
        store.record_rejection(url, reason, detail, score=evaluation["score"])


def _rejection_reason(evaluation: dict, threshold: int) -> tuple[str, str]:
    """Infer the dominant 'why-not' reason so the user can tune their criteria."""
    bd = evaluation.get("breakdown", {})
    score = evaluation.get("score", 0)
    if score == 0:
        return "not_a_company", "page non identifiée comme entreprise"
    if not evaluation.get("signal_verified"):
        return "unverified_signal", f"aucune preuve du signal recherché (score {score})"

    def _ratio(key: str) -> float:
        seg = bd.get(key, {})
        mx = seg.get("max", 1) or 1
        return seg.get("score", 0) / mx

    if _ratio("need") <= 0.25:
        return "no_need", f"besoin peu probable (score {score})"
    if _ratio("icp") == 0:
        return "off_icp", f"hors profil client idéal (score {score})"
    return "below_threshold", f"score {score} < {threshold}"


def run(cfg: ProspectConfig, store: Store, *, max_steps: int | None = None,
        on_progress=None) -> RunStats:
    """Run a prospecting hunt. `on_progress(stats)` is called after each step so a
    live dashboard can reflect progress (it reads the same SQLite the loop writes)."""
    from prospect.engine import filters, scrapers  # lazy: needs `scrape` extra
    from prospect.sources import get_sources

    def _tick(phase: str) -> None:
        stats.phase = phase
        if on_progress:
            try:
                on_progress(stats)
            except Exception:  # noqa: BLE001
                pass

    llm_light = get_provider(cfg.llm, "light")
    llm_strong = get_provider(cfg.llm, "strong")
    stats = RunStats()
    started = time.time()
    max_steps = max_steps or cfg.search.max_steps
    threshold = cfg.scoring.threshold

    sources = get_sources(cfg)
    active = []
    for src in sources:
        ok, msg = src.available(cfg)
        if ok:
            active.append(src)
            console.print(f"  [green]source[/] {src.name} — {msg}")
        else:
            console.print(f"  [dim]source {src.name} off — {msg}[/]")
    if not active:
        console.print("[red]No usable source. Install the scrape extra or enable a source.[/]")
        return stats

    queue: list[str] = []
    mode_idx = 0
    last_error = ""

    for step in range(max_steps):
        stats.steps = step + 1

        # ---- Phase 1: scrape & qualify a queued URL ---------------------- #
        if queue:
            queue = filters.prioritize_company_urls(queue, cfg.search.directories)
            url = queue.pop(0)
            if store.is_visited(url):
                continue
            store.mark_visited(url)
            stats.urls_seen += 1

            _tick(f"Analyse de {domain_of(url)} ({len(queue)} en file)")
            if not filters.is_fasttrack_company_url(url, cfg.filters.fasttrack_company_patterns):
                if not trieur.is_company_page(llm_light, url):
                    store.record_rejection(url, "not_a_company", "écarté par le Trieur")
                    continue
            try:
                page = scrapers.extract(url)
            except Exception as e:  # noqa: BLE001
                console.print(f"[yellow]extract failed[/]: {url} ({e})")
                continue
            _evaluate_lead(Lead(url=url, source=domain_of(url)), page, llm_strong, cfg, store, stats, threshold)
            _tick(f"{stats.matches} prospects · {len(queue)} en file")
            continue

        # ---- Phase 2: Scout generates the next query --------------------- #
        mode = cfg.search.modes[mode_idx % len(cfg.search.modes)]
        mode_idx += 1

        decision = scout.run_scout(
            llm_light, cfg,
            search_mode=mode,
            recent_searches=store.recent_searches(),
            visited_count=store.visited_count(),
            queue_count=len(queue),
            error=last_error,
        )
        last_error = ""
        if decision.action == "STOP":
            console.print("[cyan]Scout signalled STOP — search space exhausted.[/]")
            break
        if not decision.query:
            last_error = "Scout returned an empty query."
            continue

        store.mark_search(decision.query)
        stats.searches += 1
        console.print(f"  [blue]Scout[/] ({mode}) ▸ {decision.query}")
        _tick(f"Recherche : {decision.query[:60]}")

        url_only = 0
        for src in active:
            try:
                leads = list(src.fetch(cfg, decision.query, cfg.search.max_results_per_query))
            except Exception as e:  # noqa: BLE001
                console.print(f"  [yellow]source {src.name} failed[/]: {e}")
                last_error = f"{src.name} failed: {e}"
                continue
            for lead in leads:
                if not lead.url or store.is_visited(lead.url):
                    continue
                if filters.is_blacklisted_domain(lead.url, cfg.filters.domain_blacklist):
                    continue
                if lead.has_text:
                    store.mark_visited(lead.url)
                    stats.urls_seen += 1
                    _evaluate_lead(lead, None, llm_strong, cfg, store, stats, threshold)
                    _tick(f"{src.name} · {stats.matches} prospects")
                else:
                    if lead.url not in queue and not filters.has_reject_pattern(
                        lead.url, cfg.filters.reject_url_patterns
                    ):
                        queue.append(lead.url)
                        url_only += 1
            console.print(f"  [dim]{src.name}: {len(leads)} leads[/]")
        console.print(f"  [dim]→ {url_only} queued for scraping[/]")

    store.record_run(started, stats.steps, stats.urls_seen, stats.matches, {"searches": stats.searches})
    return stats
