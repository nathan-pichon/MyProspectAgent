"""LinkedIn source (opt-in) — finds company pages via `site:linkedin.com/company`
using the web search backend. OFF by default (LinkedIn ToS / scraping risk); the
user enables it explicitly and `doctor` shows a disclaimer.

Yields URL-only leads (the engine fetches the company page).
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Iterator

from prospect.sources.base import Lead

if TYPE_CHECKING:
    from prospect.config import ProspectConfig


class LinkedInSource:
    name = "linkedin"

    def available(self, cfg: "ProspectConfig") -> tuple[bool, str]:
        if not cfg.sources.linkedin_enabled:
            return False, "LinkedIn off (opt-in)"
        try:
            import ddgs  # noqa: F401
        except ImportError:
            return False, "LinkedIn: install the scrape extra"
        return True, "LinkedIn company search (opt-in — respect ToS)"

    def fetch(self, cfg: "ProspectConfig", query: str, limit: int) -> Iterator[Lead]:
        from prospect.engine import scrapers

        q = query if "linkedin.com/company" in query else f"site:linkedin.com/company {query}"
        try:
            urls = scrapers.search_web(q, limit)
        except Exception:  # noqa: BLE001
            urls = []
        for u in urls:
            if "linkedin.com/company" in u:
                yield Lead(url=u, source="linkedin")
