"""Utilitaires et constantes du parcours simple, partagés entre les modules."""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path

import appsettings
import image_replicate as REP
import paths
import prompts as PR
import scenes as SC
import story as S

SCENE_COUNTS = (3, 4, 5, 6)

PLAN_LIMITS = (0, *range(1, 9))  # 0 : autant que l'on veut (pour les propositions de l'IA)

PROPOSAL_CAP = 12  # plafond de sécurité quand l'IA propose « autant que l'on veut »

class NotFound(LookupError):
    pass

def _find_scene(st: dict, sid: str) -> dict:
    for sc in S.all_scenes(st):
        if sc["id"] == sid:
            return sc
    raise ValueError(f"Scène inconnue : {sid}")

def _find_plan(sc: dict, pid: str) -> tuple[int, dict]:
    for k, plan in enumerate(sc.get("plans", [])):
        if plan["id"] == pid:
            return k, plan
    raise ValueError(f"Plan inconnu : {pid}")

def _key(text: str) -> str:
    """Nom en minuscules, sans accents ni ponctuation : « Léa » et « lea » se retrouvent."""
    plain = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
    return " " + " ".join(re.findall(r"[a-z0-9]+", plain)) + " "

def shot_characters(text: str, sc: dict, framing: str) -> list[str]:
    """Personnages visibles dans un plan : ceux que son texte nomme. Sans nom, un plan large montre
    toute la scène ; un autre plan n'impose personne (l'image suit alors les locuteurs)."""
    named = [c for c in sc.get("characters", []) if _key(c) in _key(text)]
    if named:
        return named
    wide_words = " ensemble " in _key(text) or " large " in _key(text) or " wide " in _key(text)
    if framing in ("wide shot", "establishing shot") or wide_words:
        return list(sc.get("characters", []))
    return []

def _max_plans(st: dict) -> int:
    """Nombre de plans proposés par l'IA ; 0 veut dire « autant que l'on veut »."""
    value = st["settings"].get("max_plans")
    return 5 if value is None else int(value)

def _proposal_cap(st: dict) -> int:
    return _max_plans(st) or PROPOSAL_CAP

def _unique(values) -> list[str]:
    return list(dict.fromkeys(v for v in values if v))

def _characters(st: dict) -> list[str]:
    return _unique(n for sc in S.all_scenes(st) for n in sc.get("characters", []))

def _outfits(st: dict) -> list[tuple[str, str]]:
    """Tenues de l'histoire, sous forme (personnage, tenue)."""
    return _unique((char, outfit) for sc in S.all_scenes(st) for char, outfit in sc.get("outfits", {}).items()
                   if char and outfit)

def _locations(st: dict) -> list[str]:
    return _unique(sc.get("location") for sc in S.all_scenes(st))

def _aid(assets: dict, kind: str, name: str, parent: str | None = None) -> str | None:
    if kind == "location":
        return SC.match_registry(name, kind, assets)
    chars = {S.norm(a["name"]): k for k, a in assets.items() if a["kind"] == "character"}
    return PR.match_asset(assets, {"kind": kind, "name": name, "parent_name": parent}, chars)

def _slug(text: str) -> str:
    plain = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "_", plain).strip("_")[:30] or "tenue"

def _same(a: str, b: str) -> bool:
    return S.norm(a) == S.norm(b)

def _url(asset: dict, idx: int | None) -> str | None:
    if idx is None or not 0 <= idx < len(asset.get("candidates", [])):
        return None
    return paths.file_url(asset["candidates"][idx]["file"])

def available_loras() -> list[str]:
    """Fichiers LoRA du dossier des modèles ComfyUI (vide si ComfyUI n'est pas installé ici)."""
    if paths.KIDS:
        return []  # application enfants : pas de ComfyUI, donc pas de LoRA
    cfg = appsettings.config().get("comfy", {})
    folder = Path(cfg.get("models_dir", "")) / "loras"
    if not cfg.get("models_dir") or not folder.is_dir():
        return []
    return sorted(p.name for p in folder.iterdir() if p.suffix == ".safetensors")

def _ensure_token() -> None:
    REP.ensure_token()
