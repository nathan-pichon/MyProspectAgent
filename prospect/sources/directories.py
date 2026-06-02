"""Company-directory source — targets registries/directories (societe.com,
pappers.fr, ...) with the `site:` operator to surface single-company records
that often carry firmographics and contact details.

Yields URL-only leads (the engine fetches the record page).
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Iterator

from prospect.sources.base import Lead
from prospect.util import domain_of

if TYPE_CHECKING:
    from prospect.config import ProspectConfig


class DirectorySource:
    name = "directories"

    def available(self, cfg: "ProspectConfig") -> tuple[bool, str]:
        if not cfg.search.directories:
            return False, "Directories: none configured"
        try:
            import ddgs  # noqa: F401
        except ImportError:
            return False, "Directories: install the scrape extra"
        return True, f"Directories ({len(cfg.search.directories)})"

    def fetch(self, cfg: "ProspectConfig", query: str, limit: int) -> Iterator[Lead]:
        from prospect.engine import scrapers

        directories = cfg.search.directories
        # If the query already targets a directory, run it as-is; otherwise fan
        # the query across the configured directories.
        if any(d in query for d in directories):
            queries = [query]
        else:
            per = max(1, limit // max(1, len(directories)))
            queries = [(f"site:{d} {query}", per) for d in directories]  # type: ignore[misc]

        seen: set[str] = set()
        if queries and isinstance(queries[0], str):
            iterable = [(queries[0], limit)]
        else:
            iterable = queries  # type: ignore[assignment]

        for q, n in iterable:  # type: ignore[misc]
            try:
                urls = scrapers.search_web(q, n)
            except Exception:  # noqa: BLE001
                urls = []
            for u in urls:
                if u in seen:
                    continue
                # Keep only single-company records on a configured directory.
                if any(d in domain_of(u) for d in directories):
                    seen.add(u)
                    yield Lead(url=u, source="directories")
