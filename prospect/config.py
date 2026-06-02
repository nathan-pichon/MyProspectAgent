"""Configuration schema for MyProspectAgent (`prospect.config.json`).

Single source of truth shared between the static web configurator and the local
engine. The web SPA produces a JSON conforming to this schema; the engine
validates and runs it. No config is ever stored server-side, and no API key is
ever embedded here.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, ValidationError

SCHEMA_VERSION = "1.0"


class Offering(BaseModel):
    """What the freelancer sells — the supply side of the match."""
    services: list[str] = Field(
        default_factory=list, description="Concrete services offered (e.g. 'Audit MongoDB')"
    )
    expertise: list[str] = Field(
        default_factory=list, description="Technologies / domains of expertise (signals to match on)"
    )
    value_proposition: str = Field(
        default="", description="One-line pitch — why a client should care"
    )
    languages: list[str] = Field(default_factory=lambda: ["fr", "en"])
    geography: list[str] = Field(
        default_factory=list, description="Target markets (e.g. 'France', 'EU', 'Remote')"
    )

    def as_prompt_text(self) -> str:
        """Render a compact, LLM-friendly description of what we offer."""
        lines = [
            f"Services offered: {', '.join(self.services) or 'unspecified'}",
            f"Expertise / tech: {', '.join(self.expertise) or 'unspecified'}",
        ]
        if self.value_proposition:
            lines.append(f"Value proposition: {self.value_proposition}")
        lines.append(f"Target geography: {', '.join(self.geography) or 'any'}")
        lines.append(f"Languages: {', '.join(self.languages) or 'any'}")
        return "\n".join(lines)


class ICP(BaseModel):
    """Ideal Client Profile — the demand side we are looking for."""
    signals: list[str] = Field(
        default_factory=list,
        description="Must-have evidence on the company (e.g. 'uses MongoDB', 'hiring backend')",
    )
    industries: list[str] = Field(default_factory=list)
    company_sizes: list[str] = Field(
        default_factory=list, description="e.g. 'startup', 'scale-up', 'PME', '50-200'"
    )
    exclusions: list[str] = Field(
        default_factory=list, description="Hard exclusions (e.g. 'agencies', 'competitors')"
    )

    def as_prompt_text(self) -> str:
        lines = [
            f"Required signals: {', '.join(self.signals) or 'any'}",
            f"Industries: {', '.join(self.industries) or 'any'}",
            f"Company sizes: {', '.join(self.company_sizes) or 'any'}",
        ]
        if self.exclusions:
            lines.append(f"Exclusions: {', '.join(self.exclusions)}")
        return "\n".join(lines)


class Outreach(BaseModel):
    """How the prospecting email should be written. The agent drafts; it never sends."""
    sender_name: str = ""
    role_title: str = "Freelance"
    signature: str = ""
    tone: str = "direct, concis, professionnel et chaleureux"
    language: str = "fr"
    call_to_action: str = "proposer un court échange de 15 minutes"
    max_words: int = Field(default=140, ge=40, le=400)


class LLMConfig(BaseModel):
    provider: Literal["ollama", "openai", "anthropic", "lmstudio", "mistral", "groq"] = "ollama"
    # gemma4:e2b — light (~2 GB), runs on a small machine. For higher precision:
    # gemma4:e4b, qwen2.5:7b, or a cloud API key.
    model: str = "gemma4:e2b"
    base_url: str = "http://localhost:11434"
    temperature: float = 0.3
    # Ask Ollama to force a JSON-shaped response (in addition to tolerant parsing).
    json_format: bool = True
    # API keys are NEVER embedded in the shared config / never entered on the web.
    api_key_env: str = "PROSPECT_LLM_API_KEY"

    # --- Optional two-tier routing -------------------------------------- #
    # If a strong tier is set, it is used for the Qualifier + Outreacher (where
    # quality matters); Scout/Trieur stay on the light model (volume, cost).
    strong_provider: Literal[
        "ollama", "openai", "anthropic", "lmstudio", "mistral", "groq"
    ] | None = None
    strong_model: str | None = None
    strong_base_url: str | None = None
    strong_api_key_env: str = "PROSPECT_STRONG_LLM_API_KEY"

    @property
    def has_strong_tier(self) -> bool:
        return bool(self.strong_provider and self.strong_model)

    def for_role(self, role: Literal["light", "strong"]) -> "LLMConfig":
        """Return the effective LLMConfig for a role. Falls back to light when no
        strong tier is configured."""
        if role == "strong" and self.has_strong_tier:
            return LLMConfig(
                provider=self.strong_provider,  # type: ignore[arg-type]
                model=self.strong_model,  # type: ignore[arg-type]
                base_url=self.strong_base_url or self.base_url,
                temperature=self.temperature,
                json_format=self.json_format,
                api_key_env=self.strong_api_key_env,
            )
        return self


class SearchConfig(BaseModel):
    modes: list[Literal["WEB", "TECH_SIGNAL", "DIRECTORY", "LINKEDIN"]] = ["WEB", "TECH_SIGNAL"]
    directories: list[str] = Field(
        default_factory=list, description="Company directory domains to target with site:"
    )
    max_steps: int = 200
    max_results_per_query: int = 20


class RssFeed(BaseModel):
    """A signal feed (funding news, tech press, job boards revealing a stack)."""
    name: str
    url: str
    enabled: bool = True


class SourcesConfig(BaseModel):
    """Source toggles. LinkedIn is OFF by default (ToS / scraping risk)."""
    web_search_enabled: bool = True
    linkedin_enabled: bool = False  # opt-in only, with disclaimer in `doctor`
    rss_enabled: bool = True
    directories_enabled: bool = True
    rss_feeds: list[RssFeed] = Field(default_factory=list)


class ScoringConfig(BaseModel):
    threshold: int = Field(default=55, ge=0, le=100)


class FiltersConfig(BaseModel):
    domain_blacklist: list[str] = Field(default_factory=list)
    reject_url_patterns: list[str] = Field(default_factory=list)
    fasttrack_company_patterns: list[str] = Field(default_factory=list)


class ScheduleConfig(BaseModel):
    """Automatic recurring runs (managed by `mpa watch` / the dashboard)."""
    enabled: bool = False
    every_hours: float = Field(default=12.0, ge=0.25, le=168.0)
    notify: bool = True


class ProspectConfig(BaseModel):
    schema_version: str = SCHEMA_VERSION
    goal: str = Field(
        default="",
        description="Natural-language prospecting goal — the core steering intent",
    )
    offering: Offering = Field(default_factory=Offering)
    icp: ICP = Field(default_factory=ICP)
    outreach: Outreach = Field(default_factory=Outreach)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    search: SearchConfig = Field(default_factory=SearchConfig)
    sources: SourcesConfig = Field(default_factory=SourcesConfig)
    scoring: ScoringConfig = Field(default_factory=ScoringConfig)
    filters: FiltersConfig = Field(default_factory=FiltersConfig)
    schedule: ScheduleConfig = Field(default_factory=ScheduleConfig)


# --------------------------------------------------------------------------- #
# Loading / validation
# --------------------------------------------------------------------------- #

class ConfigError(Exception):
    pass


def load_config(path: str | Path) -> ProspectConfig:
    p = Path(path)
    if not p.exists():
        raise ConfigError(f"Config file not found: {p}")
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ConfigError(f"Invalid JSON in {p}: {e}") from e
    try:
        return ProspectConfig.model_validate(raw)
    except ValidationError as e:
        raise ConfigError(f"Config does not match schema:\n{e}") from e


def load_config_b64(b64: str) -> ProspectConfig:
    """Decode a base64url-inlined config (the `mpa init --b64 ...` path)."""
    import base64

    try:
        payload = base64.urlsafe_b64decode(b64 + "=" * (-len(b64) % 4))
        raw = json.loads(payload.decode("utf-8"))
    except Exception as e:  # noqa: BLE001
        raise ConfigError(f"Invalid base64 config: {e}") from e
    try:
        return ProspectConfig.model_validate(raw)
    except ValidationError as e:
        raise ConfigError(f"Config does not match schema:\n{e}") from e


def _default_rss_feeds() -> list[RssFeed]:
    from prospect.sources.rss import default_feeds

    return [RssFeed(**f) for f in default_feeds()]


def default_config() -> ProspectConfig:
    """The seed config — a credible MongoDB-audit prospecting example."""
    return ProspectConfig(
        goal=(
            "Trouver des entreprises (startups & PME tech) qui utilisent MongoDB "
            "et qui pourraient avoir besoin d'un audit de performance / sécurité MongoDB."
        ),
        offering=Offering(
            services=[
                "Audit de performance MongoDB",
                "Optimisation de schéma et d'index MongoDB",
                "Architecture backend Node.js / TypeScript",
            ],
            expertise=["MongoDB", "MongoDB Atlas", "Node.js", "TypeScript", "performance", "scaling"],
            value_proposition=(
                "J'aide les équipes tech à fiabiliser et accélérer leur base MongoDB "
                "(latence, coûts, scaling) via un audit actionnable."
            ),
            geography=["France", "Remote", "EU"],
        ),
        icp=ICP(
            signals=["uses MongoDB", "MongoDB Atlas", "hiring backend / Node.js engineers", "scaling data"],
            industries=["SaaS", "FinTech", "E-commerce", "HealthTech"],
            company_sizes=["startup", "scale-up", "PME"],
            exclusions=["agences de dev", "ESN/SSII", "concurrents consultants MongoDB"],
        ),
        outreach=Outreach(
            sender_name="",
            role_title="Consultant freelance MongoDB & Backend",
            call_to_action="proposer un court échange de 15 minutes",
        ),
        search=SearchConfig(
            # TECH_SIGNAL first: companies hiring for / publicly using the stack are the
            # highest-yield, lowest-noise leads (and the company is named on the page).
            modes=["TECH_SIGNAL", "WEB", "DIRECTORY"],
            directories=[
                "welcometothejungle.com", "boards.greenhouse.io", "jobs.lever.co",
                "jobs.ashbyhq.com", "apply.workable.com", "stackshare.io",
                "societe.com", "pappers.fr",
            ],
        ),
        sources=SourcesConfig(rss_feeds=_default_rss_feeds()),
        filters=FiltersConfig(
            domain_blacklist=[
                # Generic noise / social / encyclopedic
                "wikipedia.org", "reddit.com", "quora.com", "stackoverflow.com",
                "github.com", "medium.com", "dev.to", "youtube.com", "facebook.com",
                "twitter.com", "x.com", "pinterest.com", "tiktok.com",
                "instagram.com", "amazon.com", "ebay.com",
                # Software comparison / review aggregators (not companies that USE the tool)
                "g2.com", "capterra.com", "capterra.fr", "getapp.com", "getapp.co.uk",
                "getapp.co.nz", "getapp.com.au", "softwareadvice.com", "trustradius.com",
                "saasworthy.com", "producthunt.com", "slashdot.org", "sourceforge.net",
                "gartner.com", "appvizer.fr", "appvizer.com",
                # The MongoDB vendor itself + cloud/integration marketplaces (not prospects)
                "mongodb.com", "aws.amazon.com", "awscloud.com", "azure.microsoft.com",
                "cloud.google.com", "okta.com", "varonis.com", "datadoghq.com",
            ],
            reject_url_patterns=[
                "/blog/", "/article/", "/articles/", "/guide/", "/guides/",
                "/news/", "/actualites/", "/tutorial/", "/tutoriel/", "/docs/",
                "/documentation/", "/tag/", "/tags/", "/category/", "/categories/",
                "/search", "/recherche", "/login", "/signin", "/signup", "/register",
                "/connexion", "/inscription", "/cgu", "/cgv", "/mentions-legales",
                "/privacy", "/confidentialite", "?page=", "&page=", "?q=", "&q=",
            ],
            fasttrack_company_patterns=[
                "/about", "/about-us", "/a-propos", "/qui-sommes-nous",
                "/contact", "/contactez-nous", "/company", "/entreprise",
                "/team", "/equipe", "/careers", "/jobs", "/nous-rejoindre",
                "/recrutement", "/customers", "/clients", "/case-studies",
                "/company/",  # linkedin company pages
            ],
        ),
    )
