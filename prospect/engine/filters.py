"""Deterministic URL filters — keep the small LLM out of obvious decisions.

Fast-track (likely a company/identity page) and reject (clearly noise) patterns
bypass the Trieur LLM, saving tokens and improving precision.
"""
from __future__ import annotations

from urllib.parse import urlparse

from prospect.util import domain_of

# Applicant-tracking systems: a posting here names the company in its URL slug, so
# we treat it as an identifiable company page (no Trieur LLM call needed).
_ATS_HOSTS = (
    "boards.greenhouse.io", "jobs.lever.co", "jobs.ashbyhq.com",
    "apply.workable.com", "welcometothejungle.com",
)


def company_from_ats_url(url: str) -> str:
    """Best-effort company name from an ATS posting URL (e.g. greenhouse/lever slug)."""
    host = domain_of(url).lower()
    parts = [p for p in urlparse(url).path.strip("/").split("/") if p]
    if not parts:
        return ""
    if host.startswith(("boards.greenhouse.io", "jobs.lever.co", "jobs.ashbyhq.com", "apply.workable.com")):
        slug = parts[0]
    elif "welcometothejungle.com" in host and "companies" in parts:
        i = parts.index("companies")
        slug = parts[i + 1] if i + 1 < len(parts) else ""
    else:
        return ""
    return slug.replace("-", " ").replace("_", " ").strip().title()


def is_blacklisted_domain(url: str, blacklist: list[str]) -> bool:
    host = domain_of(url).lower()
    return any(bad.lower() in host for bad in blacklist)


def has_reject_pattern(url: str, patterns: list[str]) -> bool:
    low = url.lower()
    return any(p.lower() in low for p in patterns)


def is_fasttrack_company_url(url: str, patterns: list[str]) -> bool:
    """A URL we treat as a company/identity page without asking the LLM.

    Either it matches a fast-track path (/about, /contact, ...) or it is a bare
    domain root (homepage) — both are strong company-page signals.
    """
    low = url.lower()
    host = domain_of(url).lower()
    if any(h in host for h in _ATS_HOSTS):
        return True
    if any(p.lower() in low for p in patterns):
        return True
    parsed = urlparse(url)
    path = parsed.path.strip("/")
    # Homepage or shallow landing (e.g. acme.com, acme.com/fr).
    return path in ("", "fr", "en", "home", "index", "index.html")


def prioritize_company_urls(urls: list[str], directories: list[str]) -> list[str]:
    """Order the queue: shallow company pages first, directory hits next, deep
    paths last — so the most likely identity pages are scored early."""
    def rank(u: str) -> tuple[int, int]:
        host = domain_of(u).lower()
        depth = urlparse(u).path.strip("/").count("/")
        in_directory = any(d.lower() in host for d in directories)
        # lower rank = earlier
        return (1 if in_directory else 0, depth)

    return sorted(urls, key=rank)
