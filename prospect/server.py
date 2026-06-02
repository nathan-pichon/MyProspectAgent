"""Local dashboard server — 127.0.0.1 only, stdlib only, zero external host.

Serves the dashboard and a tiny JSON API that writes directly to the local
SQLite store, so the Kanban funnel drag & drop, 👍/👎 feedback, and outreach
edits persist for real.

Security model (personal local tool, still guarded against drive-by requests):
  * Bind to 127.0.0.1 only — never reachable from the network.
  * A random per-session token is embedded in the page and required on every
    API call (other origins can't read it, so they can't forge calls).
  * Reject requests whose Origin isn't our own.
"""
from __future__ import annotations

import json
import secrets as _stdlib_secrets
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from prospect.config import ProspectConfig
from prospect.store import PIPELINE_STATUSES, Store

TOKEN = _stdlib_secrets.token_urlsafe(16)


def _make_handler(cfg: ProspectConfig, db: str, host: str, port: int, config_path: str, scheduler):
    from prospect.dashboard.render import render

    origin_ok = {f"http://{host}:{port}", f"http://localhost:{port}"}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):  # noqa: D401
            pass

        def _send(self, code: int, body: bytes, ctype: str) -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _json(self, code: int, obj: dict) -> None:
            self._send(code, json.dumps(obj).encode("utf-8"), "application/json")

        def _guard(self) -> bool:
            if self.headers.get("X-MPA-Token") != TOKEN:
                self._json(403, {"error": "bad token"})
                return False
            origin = self.headers.get("Origin")
            if origin and origin not in origin_ok:
                self._json(403, {"error": "bad origin"})
                return False
            return True

        def do_GET(self) -> None:
            if self.path in ("/", "/index.html"):
                out = Path(".prospect_dashboard.html")
                store = Store(db)
                render(store, cfg, out)
                store.close()
                doc = out.read_text(encoding="utf-8")
                doc = doc.replace(
                    "</head>",
                    f'<script>window.__MPA_TOKEN__="{TOKEN}"</script></head>', 1,
                )
                self._send(200, doc.encode("utf-8"), "text/html; charset=utf-8")
            elif self.path == "/api/health":
                self._json(200, {"ok": True})
            elif self.path == "/api/state":
                store = Store(db)
                row = store.conn.execute(
                    "SELECT COUNT(*) n, COALESCE(MAX(first_seen),0) last FROM prospects"
                ).fetchone()
                total = store.conn.execute(
                    "SELECT COUNT(*) n FROM prospects WHERE score >= ?", (cfg.scoring.threshold,)
                ).fetchone()["n"]
                ready = store.ready_count()
                store.close()
                self._json(200, {
                    "running": scheduler.is_running(),
                    "progress": scheduler.progress(),
                    "last_run": scheduler.last_run_summary(),
                    "prospects_count": row["n"],
                    "matches_count": total,
                    "ready_count": ready,
                    "last_added": row["last"],
                })
            elif self.path == "/api/settings":
                from prospect.secrets import status as secret_status

                self._json(200, {
                    "secrets": secret_status(),
                    "schedule": cfg.schedule.model_dump(),
                    "llm": {"provider": cfg.llm.provider, "model": cfg.llm.model,
                            "has_strong": cfg.llm.has_strong_tier},
                    "goal": cfg.goal,
                    "rss": {
                        "enabled": cfg.sources.rss_enabled,
                        "feeds": [f.model_dump() for f in cfg.sources.rss_feeds],
                    },
                    "running": scheduler.is_running(),
                    "last_run": scheduler.last_run_summary(),
                })
            else:
                self._json(404, {"error": "not found"})

        def do_POST(self) -> None:
            if not self._guard():
                return
            length = int(self.headers.get("Content-Length", 0))
            try:
                payload = json.loads(self.rfile.read(length) or b"{}")
            except json.JSONDecodeError:
                self._json(400, {"error": "bad json"})
                return

            if self.path == "/api/move":
                url, status = payload.get("url"), payload.get("status")
                if status not in PIPELINE_STATUSES or not url:
                    self._json(400, {"error": "bad params"})
                    return
                store = Store(db)
                store.set_status(url, status)
                store.close()
                self._json(200, {"ok": True})
            elif self.path == "/api/feedback":
                url, value = payload.get("url"), payload.get("value")
                if url is None or value not in (-1, 0, 1):
                    self._json(400, {"error": "bad params"})
                    return
                store = Store(db)
                store.set_feedback(url, value)
                store.close()
                self._json(200, {"ok": True})
            elif self.path == "/api/email":
                # Save an edited draft, or regenerate it from scratch.
                url = payload.get("url")
                if not url:
                    self._json(400, {"error": "no url"})
                    return
                store = Store(db)
                if payload.get("regenerate"):
                    ok, result = _regenerate_email(cfg, store, url)
                    store.close()
                    if not ok:
                        self._json(400, {"error": result})
                        return
                    self._json(200, {"ok": True, **result})
                    return
                store.set_outreach(url, payload.get("subject", ""), payload.get("body", ""))
                store.close()
                self._json(200, {"ok": True})
            elif self.path == "/api/secrets":
                from prospect.secrets import KNOWN, set_secrets, status as secret_status

                updates = payload.get("updates", {})
                if not isinstance(updates, dict) or any(k not in KNOWN for k in updates):
                    self._json(400, {"error": "unknown secret key"})
                    return
                set_secrets({k: str(v) for k, v in updates.items()})
                self._json(200, {"ok": True, "secrets": secret_status()})
            elif self.path == "/api/goal":
                goal = str(payload.get("goal", "")).strip()
                cfg.goal = goal
                _save_config(cfg, config_path)
                self._json(200, {"ok": True, "goal": goal})
            elif self.path == "/api/schedule":
                from prospect.config import ScheduleConfig

                try:
                    sched = ScheduleConfig.model_validate({
                        "enabled": bool(payload.get("enabled", False)),
                        "every_hours": float(payload.get("every_hours", 12.0)),
                        "notify": bool(payload.get("notify", True)),
                    })
                except Exception as e:  # noqa: BLE001
                    self._json(400, {"error": f"bad schedule: {e}"})
                    return
                cfg.schedule = sched
                _save_config(cfg, config_path)
                scheduler.update(sched)
                self._json(200, {"ok": True, "schedule": sched.model_dump(),
                                 "running": scheduler.is_running()})
            elif self.path == "/api/run-now":
                scheduler.trigger_now()
                self._json(200, {"ok": True})
            elif self.path == "/api/rss":
                from prospect.config import RssFeed

                try:
                    feeds = [
                        RssFeed.model_validate(f)
                        for f in payload.get("feeds", [])
                        if f.get("url")
                    ]
                except Exception as e:  # noqa: BLE001
                    self._json(400, {"error": f"bad feed: {e}"})
                    return
                cfg.sources.rss_enabled = bool(payload.get("enabled", True))
                cfg.sources.rss_feeds = feeds
                _save_config(cfg, config_path)
                self._json(200, {"ok": True, "rss": {
                    "enabled": cfg.sources.rss_enabled,
                    "feeds": [f.model_dump() for f in feeds],
                }})
            else:
                self._json(404, {"error": "not found"})

    return Handler


def _regenerate_email(cfg: ProspectConfig, store: Store, url: str) -> tuple[bool, dict | str]:
    """Re-draft the outreach email for one prospect, on demand (uses the strong tier)."""
    rows = store.conn.execute(
        "SELECT company, summary, signals_found FROM prospects WHERE url=?", (url,)
    ).fetchone()
    if not rows:
        return False, "prospect not found"
    try:
        from prospect.engine import outreacher
        from prospect.llm.base import get_provider

        evaluation = {
            "company": rows["company"],
            "summary": rows["summary"],
            "signals_found": json.loads(rows["signals_found"] or "[]"),
        }
        mail = outreacher.draft(get_provider(cfg.llm, "strong"), cfg, evaluation)
    except Exception as e:  # noqa: BLE001
        return False, f"LLM error: {e}"
    store.set_outreach(url, mail["subject"], mail["body"])
    return True, mail


def _save_config(cfg: ProspectConfig, config_path: str) -> None:
    try:
        Path(config_path).write_text(cfg.model_dump_json(indent=2), encoding="utf-8")
    except OSError:
        pass


class Scheduler:
    """Runs prospecting hunts on a timer in a background thread. Configurable
    live from the dashboard. All local — no external trigger."""

    def __init__(self, cfg: ProspectConfig, db: str):
        self.cfg = cfg
        self.db = db
        self._sched = cfg.schedule
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._running = False
        self._last: dict | None = None
        self._progress: dict | None = None
        self._next_at: float = 0.0
        self._thread: threading.Thread | None = None

    def is_running(self) -> bool:
        return self._running

    def last_run_summary(self) -> dict | None:
        return self._last

    def progress(self) -> dict | None:
        return self._progress

    def update(self, sched) -> None:
        self._sched = sched
        self.cfg.schedule = sched
        self._reschedule()
        self._wake.set()

    def trigger_now(self) -> None:
        self._next_at = time.time()
        self._wake.set()

    def _reschedule(self) -> None:
        self._next_at = time.time() + self._sched.every_hours * 3600 if self._sched.enabled else 0.0

    def _run_once(self) -> None:
        from prospect.engine.digest import print_digest
        from prospect.engine.loop import run as run_loop

        self._running = True

        def _on_progress(stats) -> None:
            self._progress = {
                "phase": stats.phase, "steps": stats.steps,
                "urls_seen": stats.urls_seen, "matches": stats.matches,
                "new": len(stats.new_matches), "last_match": stats.last_match,
            }

        try:
            store = Store(self.db)
            stats = run_loop(self.cfg, store, on_progress=_on_progress)
            store.close()
            print_digest(stats.new_matches, self.cfg, notify=self._sched.notify)
            self._last = {"at": time.time(), "matches": stats.matches,
                          "new": len(stats.new_matches), "steps": stats.steps}
        except Exception as e:  # noqa: BLE001
            self._last = {"at": time.time(), "error": str(e)}
        finally:
            self._running = False
            self._progress = None

    def _loop(self) -> None:
        self._reschedule()
        while not self._stop.is_set():
            now = time.time()
            if self._next_at and now >= self._next_at and not self._running:
                self._run_once()
                self._next_at = time.time() + self._sched.every_hours * 3600 if self._sched.enabled else 0.0
            self._wake.wait(timeout=5)
            self._wake.clear()

    def start(self) -> None:
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()


def serve(cfg: ProspectConfig, db: str = "prospect.db", *, host: str = "127.0.0.1",
          port: int = 4321, open_browser: bool = True,
          config_path: str = "prospect.config.json") -> None:
    scheduler = Scheduler(cfg, db)
    scheduler.start()
    handler = _make_handler(cfg, db, host, port, config_path, scheduler)
    httpd = HTTPServer((host, port), handler)
    url = f"http://{host}:{port}/"
    if open_browser:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    print(f"Dashboard → {url}  (Ctrl+C to stop)")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        scheduler.stop()
        httpd.server_close()
