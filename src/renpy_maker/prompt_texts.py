"""Textes des prompts, lus dans des fichiers YAML que l'on peut modifier sans toucher au code.

- src/renpy_maker/prompts.yaml : tous les prompts, par défaut (livré avec le programme) ;
- prompts.yaml à côté de config.yaml (facultatif) : seulement les prompts que l'on veut changer. Ses valeurs
  remplacent celles du fichier par défaut, clé par clé ; une mise à jour du programme ne les écrase pas.

Dans un texte, ${nom} est remplacé par une valeur donnée par le programme, et ${nom|texte} donne le texte
quand la valeur est vide. $$ écrit un vrai « $ ». Les fichiers sont relus dès qu'ils changent : pas besoin de
relancer l'application.
"""

from __future__ import annotations

import re
import threading
from pathlib import Path

import yaml

from renpy_maker import paths

DEFAULT_FILE = Path(__file__).with_name("prompts.yaml")
PLACEHOLDER = re.compile(r"\$(?:\$|\{(\w+)(?:\|([^}]*))?\})")

_lock = threading.Lock()
_cache: dict = {"stamp": None, "data": None}


class PromptError(ValueError):
    """Prompt absent ou mal écrit : le message dit lequel, et dans quel fichier."""


def user_file() -> Path:
    return paths.REPO / "prompts.yaml"


def _read(path: Path) -> dict:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as e:
        raise PromptError(f"{path} : YAML invalide ({e})") from None
    if not isinstance(data, dict):
        raise PromptError(f"{path} : le fichier doit contenir des clés (« nom: texte »)")
    return data


def _merge(base: dict, over: dict) -> dict:
    out = dict(base)
    for k, v in over.items():
        out[k] = _merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def _stamp(path: Path):
    try:
        return path.stat().st_mtime_ns
    except OSError:
        return None


def load() -> dict:
    """Tous les prompts : le fichier par défaut, complété par le fichier de l'utilisateur s'il existe."""
    custom = user_file()
    if custom.resolve() == DEFAULT_FILE.resolve():
        custom = None
    stamp = (_stamp(DEFAULT_FILE), _stamp(custom) if custom else None)
    with _lock:
        if _cache["stamp"] != stamp:
            data = _read(DEFAULT_FILE)
            if custom and stamp[1] is not None:
                data = _merge(data, _read(custom))
            _cache.update(stamp=stamp, data=data)
        return _cache["data"]


def get(key: str):
    """Valeur brute d'une clé à points (« image.system »), texte ou groupe de textes."""
    node = load()
    for part in key.split("."):
        if not isinstance(node, dict) or part not in node:
            raise PromptError(f"Prompt « {key} » absent de {DEFAULT_FILE.name}")
        node = node[part]
    return node


def render(template: str, key: str = "", **values) -> str:
    def sub(m: re.Match) -> str:
        if m.group(0) == "$$":
            return "$"
        name, fallback = m.group(1), m.group(2)
        if name not in values:
            known = ", ".join(sorted(values)) or "aucune"
            raise PromptError(f"Prompt « {key} » : ${{{name}}} inconnu (variables possibles : {known})")
        value = values[name]
        text = "" if value is None else str(value)
        return fallback if fallback is not None and not text else text
    return PLACEHOLDER.sub(sub, str(template))


def t(key: str, **values) -> str:
    """Le texte d'un prompt, ses ${variables} remplies."""
    template = get(key)
    if not isinstance(template, str):
        raise PromptError(f"Prompt « {key} » : un texte est attendu, pas un groupe de clés")
    return render(template, key, **values)
