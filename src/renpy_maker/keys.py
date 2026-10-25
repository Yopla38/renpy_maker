"""Clés d'API. Ordre de recherche : variable d'environnement, fichier secrets.json de l'appareil,
puis (poste de développement) le fichier de clés ~/.config/slapsci/llm_api_keys.txt.

Une clé saisie dans l'application est écrite dans secrets.json, dans le dossier privé de l'appareil.
Elle n'est jamais renvoyée au navigateur (seul un indicateur « présente » est affiché)."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

from renpy_maker import paths

# Poste de développement seulement : sur Android, le dossier personnel n'existe pas.
LEGACY = Path(os.environ.get("HOME", "/nonexistent")) / ".config/slapsci/llm_api_keys.txt"


def _read_secrets() -> dict:
    if paths.SECRETS.exists():
        return json.loads(paths.SECRETS.read_text(encoding="utf-8") or "{}")
    return {}


def get(name: str) -> str | None:
    if os.environ.get(name):
        return os.environ[name]
    value = _read_secrets().get(name)
    if value:
        return value
    if LEGACY.exists():
        m = re.search(rf"^\s*(?:export\s+)?{name}\s*=\s*(.+?)\s*$", LEGACY.read_text(encoding="utf-8"), re.M)
        if m:
            return m.group(1).strip("'\"")
    return None


def set(name: str, value: str) -> None:
    """Enregistre une clé dans le dossier de l'appareil et l'active tout de suite."""
    data = _read_secrets()
    data[name] = value.strip()
    paths.SECRETS.parent.mkdir(parents=True, exist_ok=True)
    paths.SECRETS.write_text(json.dumps(data), encoding="utf-8")
    os.environ[name] = value.strip()


def present(name: str) -> bool:
    return bool(get(name))
