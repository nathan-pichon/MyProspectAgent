"""`mpa` command-line interface — MyProspectAgent.

Designed as a product surface (DX = UX): clear output, actionable errors.
Commands: init · validate · doctor · run · watch · dashboard · move · pipeline ·
feedback · tune · goal · version.
"""
from __future__ import annotations

import json
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from prospect import __version__
from prospect.config import (
    ConfigError,
    ProspectConfig,
    default_config,
    load_config,
    load_config_b64,
)
from prospect.store import DEFAULT_DB, PIPELINE_STATUSES, Store

app = typer.Typer(add_completion=False, help="MyProspectAgent (mpa) — agent de prospection freelance local-first.")
console = Console()

DEFAULT_CONFIG_PATH = "prospect.config.json"


def _load(config: str) -> ProspectConfig:
    try:
        return load_config(config)
    except ConfigError as e:
        console.print(f"[red]✗ Config error[/]\n{e}")
        raise typer.Exit(1)


@app.command()
def version() -> None:
    """Affiche la version installée."""
    console.print(f"MyProspectAgent (mpa) {__version__}")


@app.command()
def init(
    source: str = typer.Argument(None, help="Chemin vers un prospect.config.json (configurateur web)."),
    b64: str = typer.Option(None, "--b64", help="Config base64url inline (chemin court du web)."),
    out: str = typer.Option(DEFAULT_CONFIG_PATH, "--out", help="Où écrire la config."),
    seed: bool = typer.Option(False, "--seed", help="Écrit la config d'exemple intégrée (sans web)."),
    open_dashboard: bool = typer.Option(False, "--open/--no-open", help="Ouvrir le dashboard ensuite."),
) -> None:
    """Importe une configuration en local (fichier, inline, ou seed). Zéro serveur."""
    if seed:
        cfg = default_config()
    elif b64:
        try:
            cfg = load_config_b64(b64)
        except ConfigError as e:
            console.print(f"[red]✗[/] {e}")
            raise typer.Exit(1)
    elif source:
        cfg = _load(source)
    else:
        console.print("[red]Rien à importer.[/] Passe un fichier, --b64 <code>, ou --seed.")
        raise typer.Exit(1)

    Path(out).write_text(cfg.model_dump_json(indent=2), encoding="utf-8")
    console.print(f"[green]✓[/] Config écrite dans [bold]{out}[/]")
    console.print("Étape suivante : [bold]mpa doctor[/] puis [bold]mpa run[/]")
    if open_dashboard:
        dashboard(config=out)


@app.command()
def validate(config: str = typer.Option(DEFAULT_CONFIG_PATH, "--config", "-c")) -> None:
    """Valide un fichier de config contre le schéma."""
    cfg = _load(config)
    console.print(f"[green]✓ Config valide[/] (schema {cfg.schema_version})")
    console.print(f"  Objectif : [italic]{cfg.goal or '(vide)'}[/]")
    console.print(f"  Offre : {', '.join(cfg.offering.services) or '—'}")
    console.print(f"  Signaux ICP : {', '.join(cfg.icp.signals) or '—'}")
    console.print(f"  Sources : web={cfg.sources.web_search_enabled} rss={cfg.sources.rss_enabled} "
                  f"linkedin={cfg.sources.linkedin_enabled} directories={cfg.sources.directories_enabled}")


@app.command()
def doctor(config: str = typer.Option(DEFAULT_CONFIG_PATH, "--config", "-c")) -> None:
    """Checklist d'environnement : config, LLM, dépendances de scraping, éthique."""
    ok = True
    # 1. config
    try:
        cfg = load_config(config)
        console.print(f"[green]✓[/] Config trouvée et valide ({config})")
    except ConfigError as e:
        console.print(f"[red]✗[/] Config : {e}")
        console.print("  → lance [bold]mpa init --seed[/] pour partir d'un exemple.")
        raise typer.Exit(1)

    if not cfg.goal.strip():
        console.print("[yellow]![/] Aucun objectif défini — fixe-le via [bold]mpa goal \"...\"[/] ou ⚙ Réglages.")

    # 2. LLM
    from prospect.llm.base import check_connection

    okk, msg = check_connection(cfg.llm, "light")
    console.print(f"[{'green' if okk else 'red'}]{'✓' if okk else '✗'}[/] LLM principal : {msg}")
    ok = ok and okk
    if cfg.llm.has_strong_tier:
        okk2, msg2 = check_connection(cfg.llm, "strong")
        console.print(f"[{'green' if okk2 else 'yellow'}]{'✓' if okk2 else '!'}[/] LLM fort (Qualifier/Outreacher) : {msg2}")

    # 3. scraping deps
    try:
        import ddgs  # noqa: F401
        import playwright  # noqa: F401
        console.print("[green]✓[/] Dépendances de scraping installées (ddgs + playwright)")
    except ImportError:
        console.print("[yellow]![/] Scraping non installé. → pip install 'myprospectagent[scrape]' "
                      "puis 'playwright install chromium'")

    # 4. ethics / legal
    console.print(Panel.fit(
        "⚖️  [bold]Usage responsable[/]\n"
        "• L'agent RÉDIGE des emails mais ne les ENVOIE jamais — tu envoies depuis ton client mail.\n"
        "• N'utilise que des contacts publics. Respecte le RGPD et les opt-out (pas de spam).\n"
        "• La source LinkedIn est opt-in (respecte les ToS de LinkedIn).",
        border_style="dim",
    ))
    if not ok:
        raise typer.Exit(1)


@app.command()
def goal(
    text: str = typer.Argument(..., help="Le nouvel objectif de prospection (langage naturel)."),
    config: str = typer.Option(DEFAULT_CONFIG_PATH, "--config", "-c"),
) -> None:
    """Définit/​met à jour l'objectif de prospection dans la config."""
    cfg = _load(config)
    cfg.goal = text.strip()
    Path(config).write_text(cfg.model_dump_json(indent=2), encoding="utf-8")
    console.print(f"[green]✓[/] Objectif mis à jour :\n  [italic]{cfg.goal}[/]")


@app.command()
def run(
    config: str = typer.Option(DEFAULT_CONFIG_PATH, "--config", "-c"),
    db: str = typer.Option(DEFAULT_DB, "--db"),
    max_steps: int = typer.Option(None, "--max-steps", help="Limite le nombre d'étapes (test rapide)."),
) -> None:
    """Lance une recherche de prospects."""
    cfg = _load(config)
    from prospect.engine.digest import print_digest
    from prospect.engine.loop import run as run_loop

    store = Store(db)
    try:
        stats = run_loop(cfg, store, max_steps=max_steps)
    finally:
        store.close()
    console.print(
        f"\n[bold]Terminé[/] — {stats.steps} étapes, {stats.urls_seen} pages vues, "
        f"{stats.matches} prospects ({len(stats.new_matches)} nouveaux)."
    )
    print_digest(stats.new_matches, cfg, notify=False)
    console.print("\nVois les résultats : [bold]mpa dashboard[/]")


@app.command()
def watch(
    config: str = typer.Option(DEFAULT_CONFIG_PATH, "--config", "-c"),
    db: str = typer.Option(DEFAULT_DB, "--db"),
) -> None:
    """Lance le serveur dashboard avec planification automatique (selon la config)."""
    dashboard(config=config, db=db)


@app.command()
def dashboard(
    config: str = typer.Option(DEFAULT_CONFIG_PATH, "--config", "-c"),
    db: str = typer.Option(DEFAULT_DB, "--db"),
    port: int = typer.Option(4321, "--port"),
    open_browser: bool = typer.Option(True, "--open/--no-open"),
) -> None:
    """Démarre le dashboard local (http://127.0.0.1:4321) — 127.0.0.1 uniquement."""
    cfg = _load(config)
    from prospect.server import serve

    serve(cfg, db=db, port=port, open_browser=open_browser, config_path=config)


@app.command()
def move(
    url: str = typer.Argument(...),
    status: str = typer.Argument(..., help=f"Un de : {', '.join(PIPELINE_STATUSES)}"),
    db: str = typer.Option(DEFAULT_DB, "--db"),
) -> None:
    """Déplace un prospect dans le funnel."""
    if status not in PIPELINE_STATUSES:
        console.print(f"[red]Statut invalide.[/] Choisis parmi : {', '.join(PIPELINE_STATUSES)}")
        raise typer.Exit(1)
    store = Store(db)
    store.set_status(url, status)
    store.close()
    console.print(f"[green]✓[/] {url} → {status}")


@app.command()
def pipeline(db: str = typer.Option(DEFAULT_DB, "--db")) -> None:
    """Affiche le funnel de prospection."""
    store = Store(db)
    rows = store.get_prospects(min_score=0)
    store.close()
    if not rows:
        console.print("[dim]Aucun prospect. Lance [bold]mpa run[/].[/]")
        return
    by_status: dict[str, list[dict]] = {s: [] for s in PIPELINE_STATUSES}
    for r in rows:
        by_status.setdefault(r["status"], []).append(r)
    table = Table(title=f"Funnel — {len(rows)} prospects")
    table.add_column("Statut"); table.add_column("N", justify="right"); table.add_column("Top")
    for s in PIPELINE_STATUSES:
        items = by_status.get(s, [])
        top = ", ".join(f"{i['company']} ({i['score']})" for i in items[:3])
        table.add_row(s, str(len(items)), top)
    console.print(table)


@app.command()
def feedback(
    url: str = typer.Argument(...),
    value: int = typer.Argument(..., help="1 = 👍, -1 = 👎, 0 = neutre"),
    db: str = typer.Option(DEFAULT_DB, "--db"),
) -> None:
    """Enregistre un feedback 👍/👎 sur un prospect (alimente `mpa tune`)."""
    store = Store(db)
    store.set_feedback(url, value)
    store.close()
    console.print(f"[green]✓[/] feedback {value} pour {url}")


@app.command()
def tune(
    config: str = typer.Option(DEFAULT_CONFIG_PATH, "--config", "-c"),
    db: str = typer.Option(DEFAULT_DB, "--db"),
    apply: bool = typer.Option(False, "--apply", help="Sauvegarde le tuning sans confirmation."),
) -> None:
    """Apprend de tes 👎 pour affiner le Qualifier (tuning local, opt-in)."""
    cfg = _load(config)
    from prospect.engine import supervisor

    store = Store(db)
    try:
        suggestion = supervisor.suggest(cfg, store)
    finally:
        store.close()
    if not suggestion:
        console.print("[dim]Pas assez de 👎 pour proposer un réglage. Note des prospects avec 👎 d'abord.[/]")
        return
    console.print(Panel(suggestion, title="Règles proposées (depuis tes 👎)", border_style="cyan"))
    if not apply:
        if not typer.confirm("Appliquer ce tuning (injecté dans le Qualifier) ?"):
            console.print("[dim]Abandonné.[/]")
            return
    supervisor.save_tuning(suggestion)
    console.print(f"[green]✓[/] Tuning enregistré dans {supervisor.TUNING_FILE} — actif aux prochaines recherches.")


if __name__ == "__main__":
    app()
