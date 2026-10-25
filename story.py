"""Modèle de données de l'histoire : game_spec/story.yaml.

Une histoire = réglages du projet + synopsis + chapitres (chacun avec sa taille) + scènes + choix.
Les chemins ne sont pas stockés : ils se calculent à partir du graphe (lot F).

Règles de validation (story.validate) :
  - identifiants uniques (chapitres, scènes) ;
  - chaque choix pointe vers une scène existante ;
  - chaque chapitre a exactement `scene_count` scènes ;
  - personnages, lieux et tenues référencés existent dans le registre d'actifs ;
  - le total de scènes correspond à settings.total_scenes (si défini) ;
  - une scène sans choix doit être une fin, ou avoir une suite implicite (chapitre suivant).
"""

from __future__ import annotations

from pathlib import Path

import threading

import yaml

import paths
LOCK = threading.Lock()  # protège game_spec/story.yaml : partagé par le serveur et le pipeline
PROVIDER_ROLES = ("text", "image_base", "image_edit")
NARRATOR = "Narration"
PROVIDER_CHOICES = {
    "text": {"anthropic", "openai", "ollama", "replicate"},
    "image_base": {"replicate", "comfyui"},
    "image_edit": {"replicate", "comfyui"},
}


# Styles visuels proposés au début d'une histoire. Le suffixe est ajouté à chaque prompt d'image.
STYLES = {
    "aquarelle": {"label": "Aquarelle", "desc": "Couleurs douces, papier texturé, traits délavés",
                  "suffix": "watercolor painting, soft wet edges, visible paper texture, delicate pastel colours, "
                            "hand-painted illustration"},
    "dessin_anime": {"label": "Dessin animé", "desc": "Contours nets, couleurs vives, aplats",
                     "suffix": "2D cartoon illustration, clean ink outlines, flat cel shading, vibrant colours"},
    "huile": {"label": "Peinture à l'huile", "desc": "Touches de pinceau, lumière chaude, matière",
              "suffix": "oil painting, visible brush strokes, rich warm textures, classical lighting"},
    "realiste": {"label": "Réaliste 3D", "desc": "Rendu CGI photoréaliste, lumière de cinéma",
                 "suffix": "photorealistic 3D render, realistic CGI character, soft cinematic lighting, "
                           "detailed skin texture"},
}


def style_of(story: dict) -> dict | None:
    """Style choisi pour cette histoire, ou None. Sans choix, l'ancien réglage de config.yaml s'applique."""
    key = story.get("settings", {}).get("style")
    if key not in STYLES:
        return None
    return {"key": key, "name": STYLES[key]["label"], "positive_suffix": STYLES[key]["suffix"]}


def style_choices() -> list[dict]:
    return [{"key": k, "name": v["label"], "desc": v["desc"], "suffix": v["suffix"]} for k, v in STYLES.items()]


def new_story(title: str = "", idea: str = "", total_scenes: int = 6) -> dict:
    return {
        "version": 1,
        "title": title,
        "idea": idea,
        "settings": {
            "language": "fr",
            "explicit_content": False,          # case à cocher, désactivée par défaut
            "total_scenes": total_scenes,
            "style": None,                      # clé de STYLES, choisie au début
            "max_plans": 5,                     # plans (images) maximum par scène
            "providers": {
                "text": "anthropic",
                "image_base": "replicate",      # flux-dev
                "image_edit": "replicate",      # flux-2-klein-9b
            },
        },
        "synopsis": "",
        "chapters": [],
    }


SCENE_DEFAULTS = {"choices": [], "ending": False, "locked": False, "dialogue": [], "plans": [], "decor": []}
CHAPTER_DEFAULTS = {"locked": False, "scenes": []}


def migrate(story: dict) -> dict:
    """Complète les champs ajoutés après la création d'une histoire. Ne retire ni ne modifie rien."""
    for ch in story.get("chapters", []):
        for k, v in CHAPTER_DEFAULTS.items():
            ch.setdefault(k, [] if isinstance(v, list) else v)
        for sc in ch.get("scenes", []):
            for k, v in SCENE_DEFAULTS.items():
                if k not in sc:
                    sc[k] = [] if isinstance(v, list) else v
    return story


def load(path: Path | None = None) -> dict:
    path = path or paths.story_file()
    if not path.exists():
        return new_story()
    return migrate(yaml.safe_load(path.read_text(encoding="utf-8")) or new_story())


def save(story: dict, path: Path | None = None) -> None:
    path = path or paths.story_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(story, allow_unicode=True, sort_keys=False), encoding="utf-8")


def add_chapter(story: dict, chapter_id: str, title: str, summary: str, scene_count: int) -> dict:
    if scene_count < 1:
        raise ValueError("Un chapitre a au moins une scène")
    ch = {"id": chapter_id, "title": title, "summary": summary,
          "scene_count": scene_count, "locked": False, "scenes": []}
    story["chapters"].append(ch)
    return ch


def add_scene(chapter: dict, scene_id: str, title: str, summary: str,
              characters: list[str], location: str | None, outfits: dict[str, str]) -> dict:
    sc = {"id": scene_id, "title": title, "summary": summary, "characters": characters,
          "location": location, "outfits": outfits, "choices": [], "ending": False, "locked": False,
          "dialogue": [], "plans": []}
    chapter["scenes"].append(sc)
    return sc


def all_scenes(story: dict) -> list[dict]:
    return [sc for ch in story["chapters"] for sc in ch["scenes"]]


def validate(story: dict, assets: dict | None = None) -> list[str]:
    """Renvoie la liste des problèmes. Liste vide = histoire cohérente."""
    errors: list[str] = []
    seen_ch, seen_sc = set(), set()
    scenes = all_scenes(story)
    scene_ids = {sc["id"] for sc in scenes}

    settings = story.get("settings", {})
    for role, choices in PROVIDER_CHOICES.items():
        p = settings.get("providers", {}).get(role)
        if p not in choices:
            errors.append(f"settings.providers.{role} : '{p}' non reconnu (attendu : {sorted(choices)})")

    for ch in story["chapters"]:
        if ch["id"] in seen_ch:
            errors.append(f"chapitre en double : {ch['id']}")
        seen_ch.add(ch["id"])
        if len(ch["scenes"]) != ch["scene_count"]:
            errors.append(f"{ch['id']} : {len(ch['scenes'])} scène(s) pour une taille de {ch['scene_count']}")
        for sc in ch["scenes"]:
            where = f"{ch['id']}/{sc['id']}"
            if sc["id"] in seen_sc:
                errors.append(f"scène en double : {sc['id']}")
            seen_sc.add(sc["id"])
            for target in (c["target"] for c in sc["choices"]):
                if target not in scene_ids:
                    errors.append(f"{where} : choix vers une scène inexistante '{target}'")
            if not sc["choices"] and not sc["ending"]:
                # une scène sans choix doit être une fin, ou mener à la scène suivante
                if not _has_successor(scenes, sc):
                    errors.append(f"{where} : scène sans suite (ni choix, ni fin)")
            errors += _check_plans(where, sc)
            for i, line in enumerate(sc.get("dialogue", []), 1):
                if line.get("speaker") not in set(sc.get("characters", [])) | {NARRATOR}:
                    errors.append(f"{where} : réplique {i} : locuteur '{line.get('speaker')}' absent de la scène")
                if not str(line.get("text", "")).strip():
                    errors.append(f"{where} : réplique {i} vide")
            if assets is not None:
                errors += _check_assets(where, sc, assets)

    total = settings.get("total_scenes")
    if total is not None and len(scenes) != total:
        errors.append(f"{len(scenes)} scène(s) au total, {total} visée(s)")
    return errors


def _has_successor(scenes: list[dict], sc: dict) -> bool:
    i = next(k for k, s in enumerate(scenes) if s is sc)
    return i + 1 < len(scenes)


def _check_assets(where: str, sc: dict, assets: dict) -> list[str]:
    """Les scènes désignent personnages, lieux et tenues par leur nom (comparé sans casse)."""
    errs = []
    known = assets.get("assets", {})
    names = {kind: {norm(a.get("name", aid)) for aid, a in known.items() if a["kind"] == kind}
             for kind in ("character", "location", "outfit")}
    for cname in sc.get("characters", []):
        if norm(cname) not in names["character"]:
            errs.append(f"{where} : personnage inconnu '{cname}'")
    loc = sc.get("location")
    if loc and norm(loc) not in names["location"]:
        errs.append(f"{where} : lieu inconnu '{loc}'")
    for cname, outfit in sc.get("outfits", {}).items():
        if norm(outfit) not in names["outfit"]:
            errs.append(f"{where} : tenue inconnue '{outfit}' ({cname})")
    return errs



def norm(text: str) -> str:
    """Clé de comparaison : casse et espaces ignorés."""
    return " ".join((text or "").lower().split())


def story_elements(story: dict) -> list[dict]:
    """Éléments utilisés par l'histoire : personnages, lieux, tenues.

    Une tenue est rattachée à son personnage (parent_name). Un lieu garde le résumé de la
    première scène où il apparaît, comme point de départ de sa description.
    """
    found: dict[tuple, dict] = {}

    def add(kind: str, name: str, desc: str, parent: str | None, scene_id: str) -> None:
        key = (kind, norm(name), norm(parent or ""))
        e = found.setdefault(key, {"kind": kind, "name": name, "description": desc,
                                   "parent_name": parent, "scenes": []})
        if scene_id not in e["scenes"]:
            e["scenes"].append(scene_id)

    for sc in all_scenes(story):
        for c in sc.get("characters", []):
            add("character", c, "", None, sc["id"])
        if sc.get("location"):
            add("location", sc["location"], sc.get("summary", ""), None, sc["id"])
        for char, outfit in sc.get("outfits", {}).items():
            add("outfit", outfit, "", char, sc["id"])
    return list(found.values())


def is_locked(chapter: dict, scene: dict | None = None) -> bool:
    """Un chapitre verrouillé verrouille ses scènes. Une scène verrouillée se verrouille seule."""
    return bool(chapter.get("locked") or (scene and scene.get("locked")))


def _check_plans(where: str, sc: dict) -> list[str]:
    """Plans d'image : premier plan au début, débuts croissants et dans les répliques, personnages présents."""
    errs = []
    plans = sc.get("plans", [])
    n_lines = len(sc.get("dialogue", []))
    if plans and plans[0]["from_line"] != 0:
        errs.append(f"{where} : la première image doit commencer au début de la scène")
    starts = [p["from_line"] for p in plans]
    if starts != sorted(starts):
        errs.append(f"{where} : débuts d'images non croissants")
    for p in plans:
        if n_lines and p["from_line"] >= n_lines:
            errs.append(f"{where} : image {p['id']} commence après la dernière réplique")
        extra = set(p.get("characters", [])) - set(sc.get("characters", []))
        if extra:
            errs.append(f"{where} : image {p['id']} : personnages absents de la scène {sorted(extra)}")
    return errs
