"""Emplacements du moteur.

CODE : les fichiers du programme (lecture seule sur Android).
HOME : les données de l'histoire (écriture). Par défaut, le dossier du projet ; sur Android,
       le dossier privé de l'application, passé par RENPY_MAKER_HOME.

RENPY_MAKER_MODE=enfants : application grand public (enfants et adolescents). Le contenu explicite
est alors interdit, et les filtres de sécurité des images restent activés.
"""

from __future__ import annotations

import os
from pathlib import Path

CODE = Path(__file__).resolve().parent
HOME = Path(os.environ.get("RENPY_MAKER_HOME") or CODE)
GAME_SPEC = HOME / "game_spec"
ASSETS = HOME / "assets"
WORK = HOME / "work"
SECRETS = HOME / "secrets.json"          # clés saisies dans l'application (jamais dans le code)
KIDS = os.environ.get("RENPY_MAKER_MODE", "expert") == "enfants"
