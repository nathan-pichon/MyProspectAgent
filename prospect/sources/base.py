"""Source abstraction + registry.

A Source turns a search query into Leads (candidate companies). If a Lead
already carries `text`, the engine can score it without scraping; otherwise only
the URL is known and the engine fetches the page.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Iterator, Protocol, runtime_checkable

if TYPE_CHECKING:
    from prospect.config import ProspectConfig


@dataclass
class Lead:
    """A candidate company from a source."""
    url: str
    company: str = ""
    title: str = ""
    text: str = ""           # full page text if the source provides it
    source: str = ""         # source name (e.g. "web", "linkedin", "rss")
    posted_at: str = ""      # ISO date if known (freshness of a signal)
    extra: dict = field(default_factory=dict)

    @property
    def has_text(self) -> bool:
        return bool(self.text and len(self.text.strip()) >= 200)


@runtime_checkable
class Source(Protocol):
    name: str

    def available(self, cfg: "ProspectConfig") -> tuple[bool, str]:
        """Return (usable, message) — e.g. deps installed, opt-in enabled."""
        ...

    def fetch(self, cfg: "ProspectConfig", query: str, limit: int) -> Iterator[Lead]:
        """Yield leads for a query."""
        ...


def get_sources(cfg: "ProspectConfig") -> list["Source"]:
    """Build the ordered list of enabled sources (signal feeds first, web last)."""
    sources: list[Source] = []
    if cfg.sources.rss_enabled:
        from prospect.sources.rss import RssSource

        sources.append(RssSource())
    if cfg.sources.linkedin_enabled:
        from prospect.sources.linkedin import LinkedInSource

        sources.append(LinkedInSource())
    if cfg.sources.directories_enabled:
        from prospect.sources.directories import DirectorySource

        sources.append(DirectorySource())
    if cfg.sources.web_search_enabled:
        # Broad fallback, always last.
        from prospect.sources.web_search import WebSearchSource

        sources.append(WebSearchSource())
    return sources
