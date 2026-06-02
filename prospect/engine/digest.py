"""Digest of new prospects + optional OS notification (best-effort, macOS/Linux)."""
from __future__ import annotations

import shutil
import subprocess
import sys

from rich.console import Console

from prospect.config import ProspectConfig

console = Console()


def print_digest(new_matches: list[dict], cfg: ProspectConfig, *, notify: bool = True) -> None:
    n = len(new_matches)
    if n == 0:
        console.print("[dim]Aucun nouveau prospect lors de cette recherche.[/]")
        return
    console.print(f"\n[bold green]✦ {n} nouveau(x) prospect(s)[/]")
    for m in sorted(new_matches, key=lambda x: x.get("score", 0), reverse=True)[:10]:
        console.print(
            f"  • [bold]{m.get('company','?')}[/] — {m.get('score',0)}/100  "
            f"[dim]{m.get('industry','')}[/]"
        )
    if notify:
        _os_notify("MyProspectAgent", f"{n} nouveau(x) prospect(s) trouvé(s)")


def _os_notify(title: str, message: str) -> None:
    try:
        if sys.platform == "darwin" and shutil.which("osascript"):
            subprocess.run(
                ["osascript", "-e", f'display notification "{message}" with title "{title}"'],
                check=False, capture_output=True,
            )
        elif sys.platform.startswith("linux") and shutil.which("notify-send"):
            subprocess.run(["notify-send", title, message], check=False, capture_output=True)
    except Exception:  # noqa: BLE001
        pass
