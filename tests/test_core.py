"""Offline test suite — no LLM, no network. Run with `pytest -q`."""
from __future__ import annotations

import json

from prospect.config import LLMConfig, ProspectConfig, default_config, load_config_b64
from prospect.engine import contacts as contacts_mod
from prospect.engine import filters, qualifier
from prospect.store import Prospect, Store
from prospect.util import clamp_int, domain_of, extract_json


# --------------------------------------------------------------------------- #
# util
# --------------------------------------------------------------------------- #
def test_extract_json_fenced():
    assert extract_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert extract_json('blah {"x": "y"} trailing') == {"x": "y"}
    assert extract_json("not json") is None


def test_clamp_int():
    assert clamp_int("42", 0, 100) == 42
    assert clamp_int(200, 0, 100) == 100
    assert clamp_int(None, 0, 100, default=7) == 7


def test_domain_of():
    assert domain_of("https://acme.com/about") == "acme.com"
    assert domain_of("acme.com") == "acme.com"


# --------------------------------------------------------------------------- #
# config
# --------------------------------------------------------------------------- #
def test_default_config_valid():
    cfg = default_config()
    assert cfg.goal
    assert cfg.offering.services
    assert cfg.scoring.threshold >= 0


def test_two_tier_routing():
    cfg = LLMConfig(strong_provider="anthropic", strong_model="claude-x")
    assert cfg.has_strong_tier
    assert cfg.for_role("strong").provider == "anthropic"
    assert cfg.for_role("light").provider == "ollama"
    # no strong tier → strong falls back to light
    assert LLMConfig().for_role("strong").model == LLMConfig().model


def test_config_b64_roundtrip():
    import base64

    cfg = default_config()
    raw = cfg.model_dump_json()
    b64 = base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")
    restored = load_config_b64(b64)
    assert restored.goal == cfg.goal


# --------------------------------------------------------------------------- #
# contacts
# --------------------------------------------------------------------------- #
def test_contact_extraction_and_classification():
    text = "Contact: contact@acme.com, ceo jean.dupont@acme.com. Spam noreply@acme.com demo name@example.com"
    links = ["mailto:hello@acme.com", "https://www.linkedin.com/company/acme/", "https://twitter.com/acme"]
    c = contacts_mod.extract(text, links, "https://acme.com/contact")
    assert c.email == "jean.dupont@acme.com"          # named beats generic, on-domain
    assert c.email_type == "named"
    assert "noreply@acme.com" not in c.all_emails      # junk filtered
    assert "name@example.com" not in c.all_emails      # example filtered
    assert c.linkedin == "https://www.linkedin.com/company/acme"
    assert c.website == "https://acme.com"


def test_pick_company_website():
    anchors = [
        {"text": "Trouver un job", "href": "https://www.welcometothejungle.com/fr/jobs"},
        {"text": "Voir le site", "href": "https://teale.io"},
        {"text": "LinkedIn", "href": "https://linkedin.com/company/teale"},
    ]
    assert contacts_mod.pick_company_website(anchors, "https://www.welcometothejungle.com/fr/companies/teale") == "https://teale.io"
    # no labelled link → first plausible external
    anchors2 = [{"text": "x", "href": "https://acme.io/page"}, {"text": "li", "href": "https://linkedin.com/company/x"}]
    assert contacts_mod.pick_company_website(anchors2, "https://boards.greenhouse.io/acme") == "https://acme.io/page"
    # nothing external
    assert contacts_mod.pick_company_website([{"text": "jobs", "href": "/fr/jobs"}], "https://welcometothejungle.com/x") == ""


def test_enrich_from_website_follows_company_site():
    """ATS lead with no email → follow 'Voir le site' → extract email from the site."""
    class FakePage:
        def __init__(self, text, links=None, anchors=None):
            self.text = text; self.links = links or []; self.anchors = anchors or []

    pages = {
        "https://teale.io": FakePage(
            "Teale — santé mentale. Voir nos offres.",
            links=[], anchors=[{"text": "Contact", "href": "https://teale.io/contact"}],
        ),
        "https://teale.io/contact": FakePage(
            "Écrivez-nous : hello@teale.io", links=["mailto:hello@teale.io"],
        ),
    }
    base = contacts_mod.Contacts()  # no email (as on the WTTJ tech page)
    anchors = [{"text": "Voir le site", "href": "https://teale.io"}]
    out = contacts_mod.enrich_from_website(base, anchors, "https://www.welcometothejungle.com/fr/companies/teale/tech", lambda u: pages.get(u))
    assert out.email == "hello@teale.io"
    assert out.website == "https://teale.io"


def test_needs_enrichment_gating():
    empty = contacts_mod.Contacts()
    withmail = contacts_mod.Contacts(email="x@y.com")
    assert contacts_mod.needs_enrichment("https://www.welcometothejungle.com/fr/companies/teale/tech", empty)
    assert not contacts_mod.needs_enrichment("https://acme.com/about", empty)        # not an aggregator
    assert not contacts_mod.needs_enrichment("https://jobs.lever.co/acme", withmail)  # already has email


def test_email_classification():
    assert contacts_mod.classify_email("contact@x.com") == "generic"
    assert contacts_mod.classify_email("cto@x.com") == "role"
    assert contacts_mod.classify_email("marie.curie@x.com") == "named"


# --------------------------------------------------------------------------- #
# filters
# --------------------------------------------------------------------------- #
def test_filters():
    assert filters.is_blacklisted_domain("https://reddit.com/r/x", ["reddit.com"])
    assert filters.has_reject_pattern("https://x.com/blog/post", ["/blog/"])
    assert filters.is_fasttrack_company_url("https://acme.com/about", ["/about"])
    assert filters.is_fasttrack_company_url("https://acme.com", [])  # bare domain = homepage
    assert not filters.is_fasttrack_company_url("https://acme.com/deep/path/x", ["/about"])


def test_ats_fasttrack_and_company_name():
    # ATS job postings are fast-tracked (no Trieur LLM) and the company comes from the slug.
    gh = "https://boards.greenhouse.io/acmecloud/jobs/12345"
    lv = "https://jobs.lever.co/payflux/abc-def"
    assert filters.is_fasttrack_company_url(gh, [])
    assert filters.is_fasttrack_company_url(lv, [])
    assert filters.company_from_ats_url(gh) == "Acmecloud"
    assert filters.company_from_ats_url(lv) == "Payflux"
    wttj = "https://www.welcometothejungle.com/fr/companies/data-corp/jobs/backend_paris"
    assert filters.company_from_ats_url(wttj) == "Data Corp"
    assert filters.company_from_ats_url("https://acme.com/about") == ""


def test_aggregators_blacklisted():
    bl = default_config().filters.domain_blacklist
    for noise in ("https://www.g2.com/products/mongodb", "https://www.mongodb.com/atlas",
                  "https://getapp.com/x", "https://aws.amazon.com/marketplace"):
        assert filters.is_blacklisted_domain(noise, bl), noise


def test_prioritize_company_urls():
    urls = ["https://acme.com/a/b/c", "https://societe.com/x", "https://acme.com"]
    ordered = filters.prioritize_company_urls(urls, ["societe.com"])
    assert ordered[0] == "https://acme.com"  # shallow non-directory first


# --------------------------------------------------------------------------- #
# store
# --------------------------------------------------------------------------- #
def test_store_dedup_and_ready_count(tmp_path):
    db = str(tmp_path / "t.db")
    s = Store(db)
    p = Prospect(url="https://acme.com/about", company="Acme", website="https://acme.com",
                 email="x@acme.com", score=70, outreach_body="Bonjour")
    assert s.upsert_prospect(p) is True
    # same company, different URL, higher score, empty draft → merge, keep draft, bump score
    p2 = Prospect(url="https://acme.com/contact", company="Acme", website="https://acme.com", score=80)
    assert s.upsert_prospect(p2) is False
    rows = s.get_prospects()
    assert len(rows) == 1
    assert rows[0]["score"] == 80
    assert rows[0]["outreach_body"] == "Bonjour"   # not wiped
    assert s.ready_count() == 1
    s.close()


# --------------------------------------------------------------------------- #
# qualifier (fake LLM — no network)
# --------------------------------------------------------------------------- #
class FakeLLM:
    def __init__(self, payload: dict):
        self._payload = payload

    def complete(self, prompt: str) -> str:
        return json.dumps(self._payload)

    def health(self):
        return True, "fake"


def test_qualifier_grounded_signal_passes():
    cfg = default_config()
    text = "Acme SAS — nous utilisons MongoDB Atlas en production pour des millions de commandes."
    llm = FakeLLM({
        "score": 90, "company": "Acme SAS", "industry": "SaaS", "location": "Lyon",
        "summary": "Bon prospect.",
        "signals_found": [{"quote": "nous utilisons MongoDB Atlas en production", "signal": "uses MongoDB"}],
        "breakdown": {
            "signal": {"score": 40, "max": 40}, "need": {"score": 22, "max": 25},
            "icp": {"score": 18, "max": 20}, "reachability": {"score": 10, "max": 15},
        },
    })
    ev = qualifier.evaluate(llm, cfg, text, source_url="https://acme.com")
    assert ev["signal_verified"] is True
    assert ev["score"] == 90
    assert ev["signals_found"][0]["source_url"] == "https://acme.com"


def test_qualifier_hallucinated_signal_is_capped():
    """The model claims a signal whose quote is NOT in the source → cap + recompute."""
    cfg = default_config()
    text = "Bistro Lumière — restaurant gastronomique à Paris."
    llm = FakeLLM({
        "score": 88, "company": "Bistro", "summary": "x",
        "signals_found": [{"quote": "we use MongoDB Atlas at scale", "signal": "uses MongoDB"}],  # not in text
        "breakdown": {
            "signal": {"score": 40, "max": 40}, "need": {"score": 20, "max": 25},
            "icp": {"score": 18, "max": 20}, "reachability": {"score": 10, "max": 15},
        },
    })
    ev = qualifier.evaluate(llm, cfg, text, source_url="https://bistro.fr")
    assert ev["signal_verified"] is False
    assert ev["breakdown"]["signal"]["score"] == qualifier.SIGNAL_CAP_WITHOUT_EVIDENCE
    # total recomputed from capped sub-scores: 10 + 20 + 18 + 10 = 58
    assert ev["score"] == 58


def test_qualifier_keeps_short_known_term_quote():
    """Regression: a short quote like 'MongoDB' (7 chars) that matches a known
    target term must be accepted as verified evidence — not dropped by a blanket
    length cutoff (the bug that buried real MongoDB users in why-not)."""
    cfg = default_config()  # expertise includes "MongoDB", "Node.js"
    text = "Backend\nNode.js\n100%\nMongoDB\n100%\nFrontend\nTypeScript"
    llm = FakeLLM({
        "score": 70, "company": "Teale", "summary": "Utilise MongoDB.",
        "signals_found": [
            {"quote": "MongoDB", "signal": "uses MongoDB"},
            {"quote": "Node.js", "signal": "Node.js"},
        ],
        "breakdown": {
            "signal": {"score": 35, "max": 40}, "need": {"score": 15, "max": 25},
            "icp": {"score": 15, "max": 20}, "reachability": {"score": 5, "max": 15},
        },
    })
    ev = qualifier.evaluate(llm, cfg, text, source_url="https://wttj.test/teale")
    assert ev["signal_verified"] is True
    quotes = [s["quote"] for s in ev["signals_found"]]
    assert "MongoDB" in quotes and "Node.js" in quotes
    assert ev["breakdown"]["signal"]["score"] == 35  # not capped


def test_qualifier_reachability_is_deterministic():
    """Reachability comes from the extracted contacts, not the model's guess —
    a LinkedIn-only contact must score > 0 even if the model said 0."""
    cfg = default_config()
    text = "Acme — nous utilisons MongoDB en production."
    llm = FakeLLM({
        "score": 60, "company": "Acme", "summary": "x",
        "signals_found": [{"quote": "nous utilisons MongoDB en production", "signal": "uses MongoDB"}],
        "breakdown": {
            "signal": {"score": 35, "max": 40}, "need": {"score": 15, "max": 25},
            "icp": {"score": 15, "max": 20}, "reachability": {"score": 0, "max": 15},  # model says 0
        },
    })
    only_linkedin = contacts_mod.Contacts(linkedin="https://linkedin.com/company/acme", website="https://acme.io")
    ev = qualifier.evaluate(llm, cfg, text, contacts=only_linkedin, source_url="https://acme.io")
    assert ev["breakdown"]["reachability"]["score"] == 9  # LinkedIn present → overridden to 9
    named = contacts_mod.Contacts(email="jane.doe@acme.io", email_type="named")
    ev2 = qualifier.evaluate(llm, cfg, text, contacts=named, source_url="https://acme.io")
    assert ev2["breakdown"]["reachability"]["score"] == 15


def test_qualifier_handles_garbage_output():
    cfg = default_config()
    llm = FakeLLM({})  # empty → everything defaults to 0
    ev = qualifier.evaluate(llm, cfg, "some text", source_url="https://x.com")
    assert ev["score"] == 0
    assert ev["verdict"] == "weak"
    assert ev["company"] == "Inconnue"
