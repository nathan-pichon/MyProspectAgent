"""RSS/Atom signal feeds (stdlib only).

These surface *buying-intent signals* — funding rounds, hiring, tech-news — that
often name a company. Items carry a title + summary text, so they can be scored
without scraping; the company page (if linked) is queued for contact extraction.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from typing import TYPE_CHECKING, Iterator

import requests

from prospect.sources.base import Lead

if TYPE_CHECKING:
    from prospect.config import ProspectConfig

_TAG = re.compile(r"<[^>]+>")


def default_feeds() -> list[dict]:
    """A starter set of French/EU tech & funding signal feeds."""
    return [
        {"name": "Maddyness (FR startups)", "url": "https://www.maddyness.com/feed/", "enabled": True},
        {"name": "FrenchWeb", "url": "https://www.frenchweb.fr/feed", "enabled": True},
        {"name": "EU-Startups", "url": "https://www.eu-startups.com/feed/", "enabled": True},
    ]


def _strip(html: str) -> str:
    return _TAG.sub(" ", html or "").strip()


def _text(el, *tags: str) -> str:
    for t in tags:
        # handle namespaced and plain tags
        for child in el.iter():
            if child.tag.split("}")[-1] == t and child.text:
                return child.text
    return ""


class RssSource:
    name = "rss"

    def available(self, cfg: "ProspectConfig") -> tuple[bool, str]:
        feeds = [f for f in cfg.sources.rss_feeds if f.enabled]
        if not feeds:
            return False, "RSS: no enabled feeds configured"
        return True, f"RSS ({len(feeds)} feed(s))"

    def fetch(self, cfg: "ProspectConfig", query: str, limit: int) -> Iterator[Lead]:
        """RSS feeds ignore the query (they are signal streams); we keyword-filter
        items by the ICP signals / offering expertise to stay on-goal."""
        keywords = [k.lower() for k in (cfg.icp.signals + cfg.offering.expertise)]
        emitted = 0
        for feed in cfg.sources.rss_feeds:
            if not feed.enabled or emitted >= limit:
                continue
            try:
                resp = requests.get(feed.url, timeout=15, headers={"User-Agent": "MyProspectAgent/0.1"})
                resp.raise_for_status()
                root = ET.fromstring(resp.content)
            except Exception:  # noqa: BLE001
                continue
            # RSS <item> or Atom <entry>
            items = [e for e in root.iter() if e.tag.split("}")[-1] in ("item", "entry")]
            for item in items:
                if emitted >= limit:
                    break
                title = _strip(_text(item, "title"))
                summary = _strip(_text(item, "description", "summary", "content"))
                link = _text(item, "link") or ""
                # Atom links live in an attribute.
                if not link:
                    for child in item.iter():
                        if child.tag.split("}")[-1] == "link" and child.get("href"):
                            link = child.get("href")
                            break
                blob = f"{title} {summary}".lower()
                if keywords and not any(k in blob for k in keywords):
                    continue
                if not link:
                    continue
                yield Lead(
                    url=link,
                    title=title,
                    text=f"{title}\n\n{summary}",
                    source=f"rss:{feed.name}",
                )
                emitted += 1
