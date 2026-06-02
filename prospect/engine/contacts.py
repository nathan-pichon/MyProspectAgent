"""Deterministic contact extraction — no LLM (fast, reliable, token-free).

Pulls a contact email (classified named / role / generic), a LinkedIn company
URL, the website root, and other socials from a page's text + links. Keeping
this rule-based means a 2B model can never *invent* an email address.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import urlparse

from prospect.util import domain_of

# Emails in plain text. Conservative TLD to avoid matching version strings, etc.
_EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,24}")
_LINKEDIN_COMPANY_RE = re.compile(r"https?://[a-z]{0,3}\.?linkedin\.com/company/[^\s\"'<>)]+", re.I)
_LINKEDIN_IN_RE = re.compile(r"https?://[a-z]{0,3}\.?linkedin\.com/in/[^\s\"'<>)]+", re.I)

# Addresses we never want to surface as a usable contact.
_JUNK_LOCALPARTS = {
    "noreply", "no-reply", "donotreply", "do-not-reply", "mailer-daemon",
    "postmaster", "abuse", "webmaster",
}
_JUNK_DOMAINS = {
    "example.com", "example.org", "domain.com", "email.com", "sentry.io",
    "wixpress.com", "your-domain.com", "yourdomain.com", "test.com",
}
_EXAMPLE_LOCALPARTS = {"name", "prenom", "firstname", "lastname", "nom", "email", "you", "user"}

# Generic mailbox local-parts (low conversion). Everything else with a dot/structure
# is treated as a named/role contact.
_GENERIC_LOCALPARTS = {
    "contact", "info", "hello", "hi", "bonjour", "support", "help", "sales",
    "commercial", "team", "office", "admin", "service", "press", "presse",
    "marketing", "newsletter", "welcome", "contactus", "contacto",
}
_ROLE_LOCALPARTS = {
    "ceo", "cto", "founder", "founders", "directeur", "direction", "gerant",
    "rh", "hr", "recrutement", "jobs", "career", "careers", "bizdev",
    "partnerships", "partner", "dpo",
}


@dataclass
class Contacts:
    email: str = ""
    email_type: str = ""   # 'named' | 'role' | 'generic'
    all_emails: list[str] = field(default_factory=list)
    linkedin: str = ""     # company page preferred
    website: str = ""
    socials: list[str] = field(default_factory=list)


def classify_email(email: str) -> str:
    """Classify the value of an email's local-part for outreach."""
    local = email.split("@", 1)[0].lower()
    base = re.split(r"[.\-_+]", local)[0]
    if base in _GENERIC_LOCALPARTS or local in _GENERIC_LOCALPARTS:
        return "generic"
    if base in _ROLE_LOCALPARTS or local in _ROLE_LOCALPARTS:
        return "role"
    # A structured local-part (e.g. j.dupont, jean.dupont) reads as a person.
    if re.search(r"[._\-]", local) or len(local) >= 4:
        return "named"
    return "generic"


def _is_junk_email(email: str) -> bool:
    try:
        local, domain = email.lower().split("@", 1)
    except ValueError:
        return True
    base = re.split(r"[.\-_+]", local)[0]
    if base in _JUNK_LOCALPARTS or local in _EXAMPLE_LOCALPARTS:
        return True
    if domain in _JUNK_DOMAINS:
        return True
    # Image/asset filenames that look like emails (sprite@2x.png) — already excluded
    # by the TLD set, but guard common image extensions.
    if domain.rsplit(".", 1)[-1] in ("png", "jpg", "jpeg", "gif", "webp", "svg"):
        return True
    return False


def _email_rank(email: str, page_host: str) -> tuple[int, int]:
    """Lower = better. Prefer on-domain, then named > role > generic."""
    domain = email.split("@", 1)[1].lower()
    on_domain = 0 if (page_host and page_host in domain) else 1
    type_rank = {"named": 0, "role": 1, "generic": 2}.get(classify_email(email), 3)
    return (on_domain, type_rank)


def extract(text: str, links: list[str] | None = None, page_url: str = "") -> Contacts:
    """Extract contacts from page text + anchor hrefs."""
    links = links or []
    page_host = domain_of(page_url).lower().removeprefix("www.")
    c = Contacts()

    # --- emails: from mailto: links first, then plain text ---------------- #
    raw_emails: list[str] = []
    for href in links:
        if href.lower().startswith("mailto:"):
            addr = href[7:].split("?")[0].strip()
            if addr:
                raw_emails.append(addr)
    raw_emails.extend(_EMAIL_RE.findall(text))

    seen: set[str] = set()
    clean: list[str] = []
    for e in raw_emails:
        e = e.strip().strip(".,;:").lower()
        if e in seen or _is_junk_email(e):
            continue
        seen.add(e)
        clean.append(e)
    clean.sort(key=lambda e: _email_rank(e, page_host))
    c.all_emails = clean
    if clean:
        c.email = clean[0]
        c.email_type = classify_email(clean[0])

    # --- linkedin: prefer company page, else a personal /in/ ------------- #
    haystack = text + "\n" + "\n".join(links)
    company = _LINKEDIN_COMPANY_RE.search(haystack)
    if company:
        c.linkedin = company.group(0).rstrip("/")
    else:
        person = _LINKEDIN_IN_RE.search(haystack)
        if person:
            c.linkedin = person.group(0).rstrip("/")

    # --- website root + other socials ------------------------------------ #
    if page_url:
        parsed = urlparse(page_url)
        if parsed.scheme and parsed.netloc:
            c.website = f"{parsed.scheme}://{parsed.netloc}"
    for href in links:
        low = href.lower()
        if any(s in low for s in ("twitter.com", "x.com", "github.com", "facebook.com")):
            if href not in c.socials and href.startswith("http"):
                c.socials.append(href)

    return c
