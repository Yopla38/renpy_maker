"""Histoires (projets) : liste, création, ouverture, renommage, suppression.

Une histoire vit dans HOME/projects/<id>/ : game_spec/ (histoire, registre d'images, réglages),
assets/ (images), work/ (sauvegardes) et project.json (nom, date de création).
L'histoire d'origine (la racine HOME) apparaît aussi dans la liste, avec l'identifiant « racine » :
elle n'est ni déplacée ni renommable.

Rien n'est ouvert au démarrage : l'utilisateur choisit l'histoire (voir paths.chosen()).
Une suppression déplace le dossier dans work/corbeille/ : rien n'est effacé définitivement.
"""

from __future__ import annotations

import json
import re
import shutil
import unicodedata
from datetime import datetime
from pathlib import Path

import appsettings
import assets as A
import paths
import story as S

ORIGIN = "racine"                       # identifiant de l'histoire d'origine (racine de HOME)
META = "project.json"
LAST = "dernier.json"                   # dernière histoire ouverte, reprise au démarrage
ID_RE = re.compile(r"[a-z0-9][a-z0-9_-]{0,60}")


def slug(text: str) -> str:
    plain = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", plain).strip("-") or "histoire"


def _folder(pid: str) -> Path:
    if not ID_RE.fullmatch(pid or ""):
        raise ValueError("Identifiant d'histoire invalide")
    folder = paths.PROJECTS / pid
    if not (folder / META).exists():
        raise ValueError("Histoire introuvable")
    return folder


def _folder_of(pid: str) -> Path | None:
    return None if pid == ORIGIN else _folder(pid)


def _meta(folder: Path) -> dict:
    try:
        return json.loads((folder / META).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _write_meta(folder: Path, meta: dict) -> None:
    (folder / META).write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")


def _thumbnail(root: Path, folder: Path | None, assets: dict) -> str | None:
    """Première image retenue (personnage ou scène) : sert d'illustration à la carte."""
    for kind in ("character", "scene", "location"):
        for a in assets.values():
            idx = a.get("validated_candidate")
            if a.get("kind") != kind or idx is None or not 0 <= idx < len(a.get("candidates", [])):
                continue
            rel = a["candidates"][idx]["file"]
            if (root / rel).exists():
                return "/files/" + paths.url_prefix(folder) + rel
    return None


def _info(pid: str, folder: Path | None) -> dict:
    root = folder or paths.HOME
    spec = root / "game_spec"
    story_path = spec / "story.yaml"
    st = S.load(story_path) if story_path.exists() else None
    meta = _meta(folder) if folder else {}
    chapters = (st or {}).get("chapters", [])
    scenes = sum(len(c.get("scenes", [])) for c in chapters)
    assets = A.load(spec / "assets.yaml").get("assets", {}) if (spec / "assets.yaml").exists() else {}
    stamps = [p.stat().st_mtime for p in (story_path, spec / "assets.yaml", root / META) if p.exists()]
    name = meta.get("name") or (st or {}).get("title") or ("Histoire d'origine" if folder is None else pid)
    current = paths.chosen() and paths.active_folder() == folder
    return {
        "id": pid,
        "name": name,
        "idea": (st or {}).get("idea", ""),
        "chapters": len(chapters),
        "scenes": scenes,
        "empty": scenes == 0,
        "updated": datetime.fromtimestamp(max(stamps)).strftime("%d/%m/%Y %H:%M") if stamps else "",
        "stamp": max(stamps) if stamps else 0,
        "thumbnail": _thumbnail(root, folder, assets),
        "origin": folder is None,
        "current": current,
    }


def list_projects() -> list[dict]:
    """Histoires, la plus récemment modifiée d'abord. L'histoire d'origine n'apparaît que si elle existe."""
    out = []
    if (paths.HOME / "game_spec" / "story.yaml").exists():
        out.append(_info(ORIGIN, None))
    if paths.PROJECTS.exists():
        for folder in paths.PROJECTS.iterdir():
            if (folder / META).exists() and ID_RE.fullmatch(folder.name):
                out.append(_info(folder.name, folder))
    return sorted(out, key=lambda p: p["stamp"], reverse=True)


def current() -> dict | None:
    """L'histoire ouverte, ou None si l'utilisateur n'a encore rien choisi."""
    if not paths.chosen():
        return None
    folder = paths.active_folder()
    return _info(folder.name if folder else ORIGIN, folder)


def _unique_id(base: str) -> str:
    pid, n = base, 2
    while (paths.PROJECTS / pid).exists() or pid == ORIGIN:
        pid = f"{base}-{n}"
        n += 1
    return pid


def create(name: str, idea: str = "") -> str:
    """Crée une histoire vide. Ses choix (LLM, ComfyUI ou Replicate…) partent des valeurs de config.yaml :
    ils ne sont jamais recopiés d'une autre histoire."""
    name = " ".join(str(name).split())
    if not name:
        raise ValueError("Donne un titre à l'histoire")
    pid = _unique_id(slug(name))
    folder = paths.PROJECTS / pid
    spec = folder / "game_spec"
    spec.mkdir(parents=True)
    (folder / "assets").mkdir()
    (folder / "work").mkdir()
    S.save(S.new_story(title=name, idea=" ".join(str(idea).split())), spec / "story.yaml")
    A.save({"version": 1, "assets": {}}, spec / "assets.yaml")
    _write_meta(folder, {"name": name, "created": datetime.now().isoformat(timespec="seconds")})
    return pid


def open_project(pid: str, busy: bool) -> dict:
    if busy:
        raise ValueError("Une génération est en cours : attends qu'elle se termine avant de changer d'histoire.")
    paths.activate(_folder_of(pid))
    st = S.load()
    if appsettings.absorb_story_providers(st):
        S.save(st)
    paths.PROJECTS.mkdir(parents=True, exist_ok=True)
    (paths.PROJECTS / LAST).write_text(json.dumps({"id": pid}), encoding="utf-8")
    return current()


def restore_last() -> dict | None:
    """Au démarrage : rouvre la dernière histoire ouverte, si elle existe encore."""
    try:
        pid = json.loads((paths.PROJECTS / LAST).read_text(encoding="utf-8"))["id"]
        return open_project(pid, busy=False)
    except (OSError, ValueError, KeyError, TypeError):
        return None


def rename(pid: str, name: str) -> dict:
    if pid == ORIGIN:
        raise ValueError("L'histoire d'origine garde son nom")
    name = " ".join(str(name).split())
    if not name:
        raise ValueError("Le titre ne peut pas être vide")
    folder = _folder(pid)
    meta = _meta(folder)
    meta["name"] = name
    _write_meta(folder, meta)
    if paths.active_folder() == folder:
        return current()
    return _info(pid, folder)


def delete(pid: str) -> dict:
    """Déplace l'histoire dans work/corbeille/ (récupérable à la main)."""
    if pid == ORIGIN:
        raise ValueError("L'histoire d'origine ne peut pas être supprimée d'ici")
    folder = _folder(pid)
    if paths.active_folder() == folder:
        raise ValueError("Ouvre une autre histoire avant de supprimer celle-ci")
    trash = paths.HOME / "work" / "corbeille"
    trash.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    shutil.move(str(folder), str(trash / f"{pid}-{stamp}"))
    return {"deleted": pid, "trash": str(trash / f"{pid}-{stamp}")}
