# CLAUDE.md

Guidance for Claude Code (and contributors) working in this repository.

## Project Overview

**MyProspectAgent** (CLI: `mpa`) is an open-source, **local-first** freelance *prospecting* agent.
From a natural-language goal (e.g. "companies using MongoDB that might want a MongoDB audit"), it
finds candidate **companies**, scores each as a prospect against the goal with an explainable
rubric, extracts a contact, drafts an outreach email, and presents everything in a local dashboard.
Everything runs on the user's machine with their own LLM (Ollama by default, or an API key). There
is no hosted backend.

It is the sibling of **MyJobAgent** (which finds *job offers* for a candidate); this one finds
*clients* for a freelancer. The Python package is `prospect`; the CLI command is `mpa`.

## Setup & Run

```bash
python3 -m venv .venv && source .venv/bin/activate   # Python >= 3.11
pip install -e '.[scrape,dev]'
playwright install chromium                           # first time only
ollama serve & ollama pull gemma4:e2b                 # local LLM (default)

mpa init --seed     # write a starter prospect.config.json
mpa doctor          # environment checklist
mpa goal "..."      # set the prospecting goal
mpa run             # one prospecting run (--max-steps N for a quick test)
mpa dashboard       # local dashboard at http://127.0.0.1:4321
pytest -q           # test suite (offline, no LLM needed)
python -m eval.run  # Qualifier quality GATE
```

## Architecture

The engine is a Python package under `prospect/`:

- **`prospect/config.py`** — Pydantic schema for `prospect.config.json` (the contract shared with
  the static web configurator). Blocks: `goal`, `offering`, `icp`, `outreach`, `llm`, `search`,
  `sources`, `scoring`, `filters`, `schedule`. `default_config()` is the seed. `LLMConfig` supports
  optional **two-tier routing** (`strong_*` fields) and `json_format`.
- **`prospect/llm/`** — Bring-your-own-LLM provider layer (Protocol): `ollama` (default, HTTP
  direct, forces `format:json`), `openai_compat` (OpenAI/LM Studio/Mistral/Groq), `anthropic`.
  `get_provider(cfg, role)` routes the "light" model (Scout/Trieur) vs the optional "strong" model
  (Qualifier/Outreacher). API keys are read **locally** (env or `prospect/secrets.py`), never in
  config, never on the web.
- **`prospect/sources/`** — Pluggable sources, signal-first then web fallback: `rss` (signal feeds,
  stdlib), `linkedin` (`site:linkedin.com/company`, opt-in), `directories` (`site:<registry>`),
  `web_search` (DuckDuckGo via `ddgs`). Add a source by implementing the `Source` protocol in
  `base.py` and registering it in `get_sources()`. Sources yield `Lead`s.
- **`prospect/engine/`** — The run loop and agents:
  - **Scout** (`prompts/scout.md`) — generates the next company-finding query, seeded with
    deterministic templates derived from goal+ICP so a 2B model doesn't cold-start; or STOP.
  - **Trieur** (`prompts/trieur.md`) — classifies a URL as a company/identity page vs noise; code
    fast-track/reject patterns bypass the LLM (`filters.py`).
  - **Contacts** (`contacts.py`) — **deterministic** (regex, no LLM): email (classified
    named/role/generic), LinkedIn company URL, website. A 2B model can never invent an email.
  - **Qualifier** (`prompts/qualifier.md`) — scores a prospect 0–100 with a **typed, explainable
    breakdown** (Signal 40 / Need 25 / ICP 20 / Reachability 15 + gaps). It must **quote verbatim
    evidence** for each signal; `qualifier.py` then **verifies the quote exists in the source text**
    and caps the Signal sub-score / records `unverified_signal` otherwise (anti-hallucination).
    HARD GATES (not-a-company, signal-absent, exclusions) keep precision high — see `eval/RESULTS.md`.
  - **Outreacher** (`prompts/outreacher.md`) — drafts a French outreach email from the *verified*
    summary/signals and the extracted contacts; it must not invent facts or addresses. **Drafts
    only — never sends.**
  - **loop.py** — orchestration: leads with text (RSS) are scored directly; URL-only leads are
    queued for scraping (`scrapers.py`, Playwright + stealth → text + links in one session).
  - **digest.py** — digest of new prospects (+ OS notification). **supervisor.py** — opt-in prompt
    tuning from 👎 feedback (`mpa tune`), injected into the Qualifier via `.prospect_tuning.txt`.
- **`prospect/store/`** — Local SQLite (`prospect.db`): prospects (+ breakdown, verified signals,
  contact + email_type, outreach draft, funnel status, 👍/👎), runs, visited URLs, searches,
  rejected ("why-not").
- **`prospect/server.py`** — Local dashboard server, **127.0.0.1 only** (never exposed). Serves the
  dashboard and a token-guarded API (`/api/move`, `/api/feedback`, `/api/email`, `/api/secrets`,
  `/api/goal`, `/api/schedule`, `/api/rss`) that writes directly to SQLite. Includes the recurring
  `Scheduler` thread.
- **`prospect/dashboard/render.py`** — Self-contained HTML dashboard (light/dark): ProspectCards
  with explainable ScoreBreakdown, verified-signal evidence, contact block (email + type badge),
  editable outreach email (copy / `mailto:` prefill / regenerate), Kanban funnel (drag & drop),
  why-not section, ⚙ Settings panel (keys, schedule, RSS, goal).
- **`prospect/cli.py`** — Typer CLI: `init`, `validate`, `doctor`, `goal`, `run`, `watch`,
  `dashboard`, `move`, `pipeline`, `feedback`, `tune`, `version`.

Other top-level dirs:
- **`web/`** — Static configurator (Astro + Tailwind), deployable to GitHub Pages/Vercel with
  **zero backend**. Generates a `prospect.config.json`. Never asks for API keys.
- **`eval/`** — Matching-quality harness (the GATE). `python -m eval.run` measures
  precision/recall on a labelled dataset. Keep precision ≥ 0.70 after any Qualifier prompt change.

## Conventions

- **Local-first, no external backend.** The web stays 100% static. A local 127.0.0.1 server is OK.
- **No secrets in code or in the shared config.** Keys are local-only (`prospect/secrets.py`, env
  vars, or the dashboard ⚙ panel). The static web never collects keys.
- **The agent drafts emails but never sends them.** Public contacts only; respect GDPR/opt-out.
  LinkedIn source is opt-in (ToS).
- **Language:** agent prompts and console logs in **English** (the small local model is
  English-centric); user-facing fields (`summary`, outreach email) in **French**. Keep this.
- **Tests:** add a test in `tests/test_core.py` for new behavior; keep the suite green (offline).
- Default LLM is `gemma4:e2b`. For higher precision, set a `strong_*` tier or swap `llm.model`.
