"""Local-only secret resolution.

API keys NEVER live in the shared config nor on the web. They are read here,
locally, from (in order): an explicit override file, the OS environment, or a
git-ignored `.prospect_secrets.json` next to the working directory.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

SECRETS_FILE = ".prospect_secrets.json"

# Secret env-var names the dashboard ⚙ panel is allowed to set/read.
KNOWN = ("PROSPECT_LLM_API_KEY", "PROSPECT_STRONG_LLM_API_KEY")


def _from_file(env_name: str) -> str | None:
    p = Path(SECRETS_FILE)
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None
    val = data.get(env_name)
    return str(val) if val else None


def get_api_key(env_name: str) -> str | None:
    """Resolve an API key by env-var name. Returns None if not set anywhere."""
    return os.environ.get(env_name) or _from_file(env_name)


def set_api_key(env_name: str, value: str) -> None:
    """Persist a key locally to the git-ignored secrets file (dashboard ⚙ path)."""
    p = Path(SECRETS_FILE)
    data: dict[str, str] = {}
    if p.exists():
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            data = {}
    if value:
        data[env_name] = value
    else:
        data.pop(env_name, None)
    p.write_text(json.dumps(data, indent=2), encoding="utf-8")
    try:
        p.chmod(0o600)
    except OSError:
        pass


def set_secrets(updates: dict[str, str]) -> None:
    """Set/delete several keys at once (empty value deletes). Used by the ⚙ panel."""
    for k, v in updates.items():
        set_api_key(k, str(v))


def status() -> dict[str, bool]:
    """Return {env_name: present?} for the known keys — never the values."""
    return {name: bool(get_api_key(name)) for name in KNOWN}
