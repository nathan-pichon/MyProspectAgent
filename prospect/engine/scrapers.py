"""Web search + page extraction. Imported lazily by the loop so the rest of
the package works without the optional `scrape` extra.

DuckDuckGo (ddgs) for search; Playwright + stealth for extraction. A single
`extract()` call returns the cleaned text AND the raw links (mailto/href) in one
browser session, so contact extraction needs no second navigation.
"""
from __future__ import annotations

import random
import time
from dataclasses import dataclass, field

USER_AGENTS = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Safari/605.1.15",
]

NOISE_SELECTORS = [
    "nav", "header", "footer", "aside",
    "[class*='cookie']", "[class*='Cookie']", "[id*='cookie']",
    "[class*='consent']", "[class*='banner']", "[class*='menu']",
    "[class*='share']", "[class*='newsletter']", "[class*='popup']",
    "[class*='modal']", "[class*='gdpr']", "[class*='advert']", "[class*='ad-']",
    "script", "style", "noscript", "iframe", "svg",
]

# Company/identity-oriented main-content hints (fall back to <body>).
MAIN_CONTENT_SELECTORS = [
    "main", "article", "[role='main']",
    ".about", ".about-us", ".company", ".hero", ".content", "#content",
    "[class*='about']", "[class*='company']", "[class*='hero']",
]


@dataclass
class Page:
    url: str
    text: str = ""
    html: str = ""
    links: list[str] = field(default_factory=list)  # all hrefs incl. mailto:
    title: str = ""

    @property
    def ok(self) -> bool:
        return bool(self.text and len(self.text.strip()) >= 100)


def search_web(query: str, max_results: int = 20) -> list[str]:
    from ddgs import DDGS

    urls: list[str] = []

    def _run(q: str) -> None:
        try:
            with DDGS() as ddgs:
                for r in ddgs.text(q, max_results=max_results):
                    href = r.get("href")
                    if href and href not in urls:
                        urls.append(href)
        except Exception as e:  # noqa: BLE001
            print(f"[ddgs] search error: {e}")

    _run(query)
    if not urls and "site:" in query:
        domain = query.split("site:")[1].split()[0]
        _run(query.replace(f"site:{domain}", domain))
    return urls


def extract(url: str, max_chars: int = 6000) -> Page:
    """Fetch a page once and return cleaned text + raw links + title."""
    from playwright.sync_api import sync_playwright

    try:
        from playwright_stealth import Stealth
    except ImportError:
        Stealth = None  # type: ignore

    page_obj = Page(url=url)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=random.choice(USER_AGENTS),
            locale="fr-FR",
            viewport={"width": 1920, "height": 1080},
        )
        page = context.new_page()
        if Stealth is not None:
            try:
                Stealth().apply_stealth_sync(page)
            except Exception:  # noqa: BLE001
                pass
        try:
            time.sleep(random.uniform(0.8, 2.0))
            page.goto(url, wait_until="domcontentloaded", timeout=25000)
            page.wait_for_timeout(1500)
            # Grab links + title BEFORE stripping noise (footers carry contacts).
            page_obj.links = _collect_links(page)
            try:
                page_obj.title = (page.title() or "").strip()
            except Exception:  # noqa: BLE001
                pass
            _strip_noise(page)
            raw = _main_content(page)
            page_obj.text = _clean(raw, max_chars) if raw else ""
        except Exception as e:  # noqa: BLE001
            print(f"[playwright] extract error on {url}: {e}")
        finally:
            context.close()
            browser.close()
    return page_obj


def extract_text(url: str, max_chars: int = 6000) -> str:
    """Convenience wrapper returning just the cleaned text."""
    return extract(url, max_chars).text


def _collect_links(page) -> list[str]:
    js = "(() => Array.from(document.querySelectorAll('a[href]')).map(a => a.getAttribute('href')))()"
    try:
        hrefs = page.evaluate(js) or []
    except Exception:  # noqa: BLE001
        return []
    return [h for h in hrefs if isinstance(h, str) and h.strip()]


def _strip_noise(page) -> None:
    js = """(() => { const s = %s; s.forEach(sel => { try {
        document.querySelectorAll(sel).forEach(el => el.remove()); } catch(e){} }); })()""" % (
        str(NOISE_SELECTORS).replace("'", '"')
    )
    try:
        page.evaluate(js)
    except Exception:  # noqa: BLE001
        pass


def _main_content(page) -> str:
    best = ""
    for sel in MAIN_CONTENT_SELECTORS:
        try:
            el = page.query_selector(sel)
            if el:
                text = el.inner_text().strip()
                if len(text) > len(best):
                    best = text
                if len(best) > 600:
                    return best
        except Exception:  # noqa: BLE001
            continue
    if len(best) > 200:
        return best
    body = page.query_selector("body")
    return body.inner_text().strip() if body else best


def _clean(text: str, max_chars: int) -> str:
    lines, prev = [], None
    for line in text.splitlines():
        s = line.strip()
        if s and len(s) > 2 and s != prev:
            lines.append(s)
            prev = s
    out = "\n".join(lines)
    return out[:max_chars] + "\n[...truncated...]" if len(out) > max_chars else out
