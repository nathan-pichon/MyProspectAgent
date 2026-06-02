"""Local SQLite persistence — everything stays on the user's machine.

Tracks prospects (with explainable confidence breakdown, verified signals, and a
drafted outreach email), runs, the prospecting funnel status, the user's 👍/👎
feedback, and a "why-not" log of discarded leads.
"""
from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from prospect.util import domain_of

DEFAULT_DB = "prospect.db"

# The prospecting funnel.
PIPELINE_STATUSES = ("found", "qualified", "contacted", "replied", "meeting", "won", "lost")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS prospects (
    url             TEXT PRIMARY KEY,
    dedup_key       TEXT,
    company         TEXT,
    website         TEXT,
    email           TEXT,
    email_type      TEXT,        -- 'named' | 'role' | 'generic' | ''
    linkedin        TEXT,
    location        TEXT,
    industry        TEXT,
    score           INTEGER,
    breakdown       TEXT,        -- JSON: per-criterion sub-scores + gaps
    summary         TEXT,        -- French, user-facing: why it matches
    signals_found   TEXT,        -- JSON: [{quote, source_url}] verified evidence
    outreach_subject TEXT,
    outreach_body   TEXT,        -- French draft (never auto-sent)
    source          TEXT,
    sources         TEXT,        -- JSON list of urls merged via dedup
    status          TEXT DEFAULT 'found',
    feedback        INTEGER DEFAULT 0,   -- 1=👍, -1=👎, 0=none
    first_seen      REAL,
    last_seen       REAL
);
CREATE INDEX IF NOT EXISTS idx_prospects_score ON prospects(score);
CREATE INDEX IF NOT EXISTS idx_prospects_dedup ON prospects(dedup_key);
CREATE INDEX IF NOT EXISTS idx_prospects_status ON prospects(status);

CREATE TABLE IF NOT EXISTS runs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at  REAL,
    ended_at    REAL,
    steps       INTEGER,
    urls_seen   INTEGER,
    matches     INTEGER,
    stats       TEXT
);

CREATE TABLE IF NOT EXISTS visited (
    url        TEXT PRIMARY KEY,
    visited_at REAL
);

CREATE TABLE IF NOT EXISTS searches (
    query      TEXT PRIMARY KEY,
    ran_at     REAL
);

-- "Why-not": leads the engine looked at but discarded, with the reason.
CREATE TABLE IF NOT EXISTS rejected (
    url        TEXT PRIMARY KEY,
    reason     TEXT,        -- "below_threshold", "not_a_company", "unverified_signal", "excluded", ...
    detail     TEXT,        -- human-readable
    score      INTEGER,
    seen_at    REAL
);
CREATE INDEX IF NOT EXISTS idx_rejected_reason ON rejected(reason);
"""


@dataclass
class Prospect:
    url: str
    company: str = ""
    website: str = ""
    email: str = ""
    email_type: str = ""
    linkedin: str = ""
    location: str = ""
    industry: str = ""
    score: int = 0
    breakdown: dict[str, Any] = field(default_factory=dict)
    summary: str = ""
    signals_found: list[dict] = field(default_factory=list)
    outreach_subject: str = ""
    outreach_body: str = ""
    source: str = ""

    @property
    def dedup_key(self) -> str:
        """Dedup by company name, falling back to the website/url domain — the
        same company found via several URLs is one prospect."""
        import re

        norm = lambda s: re.sub(r"\s+", " ", (s or "").lower().strip())  # noqa: E731
        company = norm(self.company)
        host = domain_of(self.website or self.url).lower().removeprefix("www.")
        return company or host or norm(self.url)


class Store:
    def __init__(self, path: str | Path = DEFAULT_DB):
        self.path = str(path)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(_SCHEMA)
        self.conn.commit()

    # --- prospects -------------------------------------------------------- #
    def upsert_prospect(self, p: Prospect) -> bool:
        """Insert or merge a prospect (dedup by company/domain).

        Returns True if this was a brand-new prospect (for digests/notifications).
        """
        now = time.time()
        cur = self.conn.execute(
            "SELECT url, sources FROM prospects WHERE dedup_key = ? OR url = ?",
            (p.dedup_key, p.url),
        )
        existing = cur.fetchone()
        if existing:
            sources = set(json.loads(existing["sources"] or "[]"))
            sources.add(p.url)
            # Keep the best info we have: take the higher score, and never wipe an
            # existing contact / summary / draft with an empty incoming value.
            self.conn.execute(
                """UPDATE prospects SET last_seen=?,
                   score=MAX(score, ?),
                   breakdown=CASE WHEN ? >= score THEN ? ELSE breakdown END,
                   summary=COALESCE(NULLIF(?, ''), summary),
                   signals_found=CASE WHEN ? != '[]' THEN ? ELSE signals_found END,
                   email=COALESCE(NULLIF(?, ''), email),
                   email_type=COALESCE(NULLIF(?, ''), email_type),
                   linkedin=COALESCE(NULLIF(?, ''), linkedin),
                   website=COALESCE(NULLIF(?, ''), website),
                   outreach_subject=COALESCE(NULLIF(?, ''), outreach_subject),
                   outreach_body=COALESCE(NULLIF(?, ''), outreach_body),
                   sources=? WHERE url=?""",
                (now, p.score, p.score, json.dumps(p.breakdown, ensure_ascii=False),
                 p.summary,
                 json.dumps(p.signals_found, ensure_ascii=False),
                 json.dumps(p.signals_found, ensure_ascii=False),
                 p.email, p.email_type, p.linkedin, p.website,
                 p.outreach_subject, p.outreach_body,
                 json.dumps(sorted(sources)), existing["url"]),
            )
            self.conn.commit()
            return False
        self.conn.execute(
            """INSERT INTO prospects
               (url, dedup_key, company, website, email, email_type, linkedin, location,
                industry, score, breakdown, summary, signals_found, outreach_subject,
                outreach_body, source, sources, first_seen, last_seen)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (p.url, p.dedup_key, p.company, p.website, p.email, p.email_type, p.linkedin,
             p.location, p.industry, p.score, json.dumps(p.breakdown, ensure_ascii=False),
             p.summary, json.dumps(p.signals_found, ensure_ascii=False), p.outreach_subject,
             p.outreach_body, p.source, json.dumps([p.url]), now, now),
        )
        self.conn.commit()
        return True

    def get_prospects(self, min_score: int = 0, status: str | None = None) -> list[dict]:
        q = "SELECT * FROM prospects WHERE score >= ?"
        params: list[Any] = [min_score]
        if status:
            q += " AND status = ?"
            params.append(status)
        q += " ORDER BY score DESC"
        rows = self.conn.execute(q, params).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["breakdown"] = json.loads(d.get("breakdown") or "{}")
            d["signals_found"] = json.loads(d.get("signals_found") or "[]")
            d["sources"] = json.loads(d.get("sources") or "[]")
            out.append(d)
        return out

    def set_status(self, url: str, status: str) -> None:
        if status not in PIPELINE_STATUSES:
            raise ValueError(f"Invalid status: {status}")
        self.conn.execute("UPDATE prospects SET status=? WHERE url=?", (status, url))
        self.conn.commit()

    def set_feedback(self, url: str, feedback: int) -> None:
        self.conn.execute(
            "UPDATE prospects SET feedback=? WHERE url=?", (max(-1, min(1, feedback)), url)
        )
        self.conn.commit()

    def set_outreach(self, url: str, subject: str, body: str) -> None:
        self.conn.execute(
            "UPDATE prospects SET outreach_subject=?, outreach_body=? WHERE url=?",
            (subject, body, url),
        )
        self.conn.commit()

    def quality_stats(self) -> dict[str, int]:
        row = self.conn.execute(
            "SELECT SUM(feedback=1) up, SUM(feedback=-1) down, COUNT(*) total FROM prospects"
        ).fetchone()
        return {"up": row["up"] or 0, "down": row["down"] or 0, "total": row["total"] or 0}

    def ready_count(self) -> int:
        """Qualified prospects with a contact AND a drafted email — the metric
        that matters (actionable leads, not URLs scanned)."""
        return self.conn.execute(
            """SELECT COUNT(*) c FROM prospects
               WHERE (email != '' OR linkedin != '')
               AND outreach_body != ''"""
        ).fetchone()["c"]

    # --- "Why-not": rejected leads ---------------------------------------- #
    def record_rejection(self, url: str, reason: str, detail: str = "", score: int = 0) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO rejected (url, reason, detail, score, seen_at) VALUES (?,?,?,?,?)",
            (url, reason, detail, score, time.time()),
        )
        self.conn.commit()

    def get_rejections(self, limit: int = 100) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM rejected ORDER BY score DESC, seen_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]

    def rejection_summary(self) -> dict[str, int]:
        rows = self.conn.execute(
            "SELECT reason, COUNT(*) c FROM rejected GROUP BY reason ORDER BY c DESC"
        ).fetchall()
        return {r["reason"]: r["c"] for r in rows}

    # --- crawl bookkeeping ------------------------------------------------ #
    def is_visited(self, url: str) -> bool:
        return self.conn.execute("SELECT 1 FROM visited WHERE url=?", (url,)).fetchone() is not None

    def mark_visited(self, url: str) -> None:
        self.conn.execute("INSERT OR REPLACE INTO visited VALUES (?,?)", (url, time.time()))
        self.conn.commit()

    def visited_count(self) -> int:
        return self.conn.execute("SELECT COUNT(*) c FROM visited").fetchone()["c"]

    def recent_searches(self, limit: int = 15) -> list[str]:
        rows = self.conn.execute(
            "SELECT query FROM searches ORDER BY ran_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [r["query"] for r in rows]

    def mark_search(self, query: str) -> None:
        self.conn.execute("INSERT OR REPLACE INTO searches VALUES (?,?)", (query, time.time()))
        self.conn.commit()

    def record_run(self, started: float, steps: int, urls_seen: int, matches: int, stats: dict) -> None:
        self.conn.execute(
            "INSERT INTO runs (started_at, ended_at, steps, urls_seen, matches, stats) VALUES (?,?,?,?,?,?)",
            (started, time.time(), steps, urls_seen, matches, json.dumps(stats, ensure_ascii=False)),
        )
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()
