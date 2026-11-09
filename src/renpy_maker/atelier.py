"""Atelier : création pas à pas. On propose un élément, l'auteur accepte ou change, puis on passe au suivant.

Une scène commence à chaque nouveau lieu. Dans une scène, on ajoute un moment à la fois : une réplique
proposée par l'IA (que l'auteur peut changer), puis l'image de ce moment (son prompt, ses références).
Les fonctions ici n'appellent le modèle de langage que pour proposer ; elles n'écrivent rien sans
qu'on le leur demande.
"""

from __future__ import annotations

import re
import unicodedata

from renpy_maker import appsettings, assets as A, llm, prompts as PR, story as S
from renpy_maker.prompt_texts import t


def _slug(text: str) -> str:
    plain = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "_", plain).strip("_") or "x"


def _story(st: dict | None = None) -> dict:
    return st if st is not None else S.load()


def _known_names(st: dict) -> list[str]:
    return sorted({n for sc in S.all_scenes(st) for n in sc.get("characters", [])})


def _known_locations(st: dict) -> list[str]:
    return sorted({sc.get("location") for sc in S.all_scenes(st) if sc.get("location")})


def propose_characters(idea: str, existing: list[str], count: int = 3, provider: str | None = None) -> list[dict]:
    """Propose des personnages qui ne sont pas encore dans l'histoire. Rien n'est enregistré."""
    system = t("atelier.characters.system", descriptor_hint=t("atelier.descriptor_hint"))
    user = t("atelier.characters.user", idea=idea, existing=", ".join(existing), count=count)
    raw = llm.extract_json(llm.complete_task("histoire", system, user, provider or appsettings.provider("text")))
    out = []
    for item in (raw.get("characters") or [])[:count]:
        name = " ".join(str(item.get("name", "")).split())
        if not name or name in existing:
            continue
        descriptor = str(item.get("descriptor", "")).strip().lower()
        out.append({"name": name, "description": " ".join(str(item.get("description", "")).split()),
                    "descriptor": descriptor if PR.valid_descriptor(descriptor) else ""})
    return out


def add_character(name: str, description: str, descriptor: str) -> str:
    """Ajoute un personnage au registre d'images (sans image : elle se dessine ensuite)."""
    name = " ".join(str(name).split())
    if not name:
        raise ValueError("Le personnage a besoin d'un nom")
    st = _story()
    with A.LOCK:
        data = A.load()
        existing = next((aid for aid, a in data["assets"].items()
                         if a["kind"] == "character" and S.norm(a["name"]) == S.norm(name)), None)
        if existing:
            return existing
        aid, n = f"char_{_slug(name)}", 2
        base = aid
        while aid in data["assets"]:
            aid, n = f"{base}_{n}", n + 1
        A.add_asset(data, aid, "character", name, description)
        data["assets"][aid]["descriptor"] = descriptor if PR.valid_descriptor(descriptor) else ""
        A.save(data)
    return aid


def propose_location(idea: str, existing: list[str], context: str = "", provider: str | None = None) -> dict:
    """Propose un lieu pour la prochaine scène. Rien n'est enregistré."""
    system = t("atelier.location.system")
    user = t("atelier.location.user", idea=idea, existing=", ".join(existing), before=context)
    raw = llm.extract_json(llm.complete_task("histoire", system, user, provider or appsettings.provider("text")))
    return {"name": " ".join(str(raw.get("name", "")).split()),
            "description": " ".join(str(raw.get("description", "")).split())}


def start_scene(title: str, location: str, characters: list[str], summary: str = "") -> str:
    """Nouvelle scène : c'est le changement de lieu qui la déclenche. Renvoie son identifiant."""
    st = _story()
    if not location.strip():
        raise ValueError("Une scène a besoin d'un lieu")
    if not st["chapters"]:
        S.add_chapter(st, "ch1", "Chapitre 1", "", 1)
    ch = st["chapters"][-1]
    numbers = [int(sc["id"][1:]) for sc in S.all_scenes(st) if sc["id"][1:].isdigit()]
    sid = f"s{max(numbers, default=0) + 1}"
    S.add_scene(ch, sid, title.strip() or location.strip(), summary.strip(), list(characters), location.strip(), {})
    ch["scene_count"] = len(ch["scenes"])
    S.save(st)
    _ensure_location(location.strip(), summary.strip())
    return sid


def _ensure_location(name: str, description: str) -> str:
    """Le lieu existe dans le registre d'images : il pourra recevoir une image."""
    with A.LOCK:
        data = A.load()
        found = next((aid for aid, x in data["assets"].items()
                      if x["kind"] == "location" and S.norm(x["name"]) == S.norm(name)), None)
        if found:
            return found
        aid, n = f"loc_{_slug(name)}", 2
        base = aid
        while aid in data["assets"]:
            aid, n = f"{base}_{n}", n + 1
        A.add_asset(data, aid, "location", name, description)
        A.save(data)
        return aid


def _scene_context(st: dict, sid: str) -> tuple[dict, list[str]]:
    sc = next(s for s in S.all_scenes(st) if s["id"] == sid)
    return sc, list(sc.get("characters", []))


def propose_line(sid: str, provider: str | None = None) -> dict:
    """Propose la prochaine réplique de la scène : une seule, avec son locuteur. Rien n'est enregistré."""
    st = _story()
    sc, present = _scene_context(st, sid)
    speakers = present + [S.NARRATOR]
    recent = sc.get("dialogue", [])[-6:]
    history = "\n".join(f"{l['speaker']} : {l['text']}" for l in recent)
    system = t("atelier.line.system", speakers=", ".join(speakers))
    user = t("atelier.line.user", story=st.get("idea") or st.get("synopsis") or "", title=sc.get("title", ""),
             summary=sc.get("summary", ""), location=sc.get("location"), present=", ".join(present), history=history)
    raw = llm.extract_json(llm.complete_task("dialogue", system, user, provider or appsettings.provider("text")))
    speaker = str(raw.get("speaker", "")).strip()
    if speaker not in speakers:
        speaker = S.NARRATOR
    return {"speaker": speaker, "text": " ".join(str(raw.get("text", "")).split())}


def add_moment(sid: str, speaker: str, text: str, pid: str | None = None) -> str:
    """Ajoute une réplique à la fin de la scène, avec son image (un plan qui commence à cette réplique).
    Renvoie l'identifiant du plan. Le prompt de l'image se propose ensuite."""
    text = " ".join(str(text).split())
    if not text:
        raise ValueError("La réplique est vide")
    st = _story()
    sc, present = _scene_context(st, sid)
    if speaker != S.NARRATOR and speaker not in present:
        raise ValueError(f"{speaker} n'est pas présent dans cette scène")
    index = len(sc.get("dialogue", []))
    sc.setdefault("dialogue", []).append({"speaker": speaker, "text": text, "expression": "neutre"})
    with A.LOCK:
        data = A.load()
        asset_id = f"scene_{sid}_m{index + 1}"
        n = 2
        base = asset_id
        while asset_id in data["assets"]:
            asset_id, n = f"{base}_{n}", n + 1
        A.add_asset(data, asset_id, "scene", f"{sc.get('title', sid)} — réplique {index + 1}", "")
        A.save(data)
    used = {p["id"] for p in sc.get("plans", [])}
    plan_id = pid or next(f"p{n}" for n in range(1, len(used) + 2) if f"p{n}" not in used)
    sc.setdefault("plans", []).append({"id": plan_id, "from_line": index, "asset": asset_id,
                                       "characters": list(present),  # tout le casting présent dans la scène
                                       "shot": {"framing": "", "angle": "", "note": ""}})
    S.save(st)
    return plan_id


def set_idea(title: str, idea: str) -> None:
    """Le point de départ : titre et idée de l'histoire. Ne génère rien."""
    idea = " ".join(str(idea).split())
    if not idea:
        raise ValueError("Décrivez votre histoire en quelques mots")
    st = _story()
    st["title"] = " ".join(str(title).split()) or st.get("title") or "Mon histoire"
    st["idea"] = idea
    S.save(st)


def propose_outfits(character: str, description: str, idea: str, existing: list[str], count: int = 3,
                    provider: str | None = None) -> list[dict]:
    """Propose des tenues pour un personnage, distinctes des tenues déjà présentes. Rien n'est enregistré."""
    system = t("atelier.outfits.system")
    user = t("atelier.outfits.user", idea=idea, character=character, description=description,
             existing=", ".join(existing), count=count)
    raw = llm.extract_json(llm.complete_task("histoire", system, user, provider or appsettings.provider("text")))
    out = []
    taken = {S.norm(n) for n in existing}
    for item in (raw.get("outfits") or []):
        name = " ".join(str(item.get("name", "")).split())
        if not name or S.norm(name) in taken:
            continue
        taken.add(S.norm(name))
        out.append({"name": name, "description": " ".join(str(item.get("description", "")).split())})
        if len(out) == count:
            break
    return out


def set_default_outfit(character_aid: str, outfit_aid: str) -> None:
    """Tenue par défaut d'un personnage : sa vignette et la référence des autres tenues. Vide : aucune."""
    with A.LOCK:
        data = A.load()
        char = data["assets"].get(character_aid)
        if char is None or char["kind"] != "character":
            raise ValueError("Personnage inconnu")
        if outfit_aid:
            outfit = data["assets"].get(outfit_aid)
            if outfit is None or outfit["kind"] != "outfit" or outfit.get("parent") != character_aid:
                raise ValueError("Cette tenue n'appartient pas à ce personnage")
            char["default_outfit"] = outfit_aid
        else:
            char.pop("default_outfit", None)
        A.save(data)



def propose_shot(sid: str, pid: str, previous: str = "", provider: str | None = None) -> str:
    """Ce que l'on voit à l'écran pour un moment, proposé par l'IA, en tenant compte des répliques qui précèdent
    et des images déjà décrites. Rien n'est enregistré."""
    st = _story()
    sc, present = _scene_context(st, sid)
    ordered = sorted(sc.get("plans", []), key=lambda p: (p["from_line"], 0 if p.get("pause") else 1))
    idx = next((i for i, p in enumerate(ordered) if p["id"] == pid), None)
    if idx is None:
        raise ValueError("Image inconnue dans cette scène")
    plan = ordered[idx]
    dialogue = sc.get("dialogue", [])
    start = plan["from_line"]
    end = ordered[idx + 1]["from_line"] if idx + 1 < len(ordered) else len(dialogue)
    before = dialogue[max(0, start - 6):start]
    covered = dialogue[start:max(start, end)]
    earlier = [p.get("shot", {}).get("note", "") for p in ordered[:idx] if p.get("shot", {}).get("note")][-3:]
    fmt = lambda lines: "\n".join(f"{l['speaker']} : {l['text']}" for l in lines)  # noqa: E731
    system = " ".join([t("atelier.shot.system")] + ([t("atelier.shot.avoid_previous")] if previous else [])
                      + [t("atelier.shot.follow")])
    user = t("atelier.shot.user", title=sc.get("title", ""), summary=sc.get("summary", ""),
             location=sc.get("location"), present=", ".join(present), before=fmt(before), covered=fmt(covered),
             earlier=" | ".join(earlier), previous=previous)
    text = llm.complete_task("dialogue", system, user, provider or appsettings.provider("text"))
    return " ".join(str(text).split()).strip('"')



def propose_viewpoints(location: str, description: str, idea: str, existing: list[str], count: int = 3,
                       provider: str | None = None) -> list[dict]:
    """Propose des points de vue pour un lieu : des angles différents du même endroit. Rien n'est enregistré."""
    system = t("atelier.viewpoints.system")
    user = t("atelier.viewpoints.user", idea=idea, location=location, description=description,
             existing=", ".join(existing), count=count)
    raw = llm.extract_json(llm.complete_task("histoire", system, user, provider or appsettings.provider("text")))
    out, taken = [], {S.norm(n) for n in existing}
    for item in (raw.get("viewpoints") or []):
        name = " ".join(str(item.get("name", "")).split())
        if not name or S.norm(name) in taken:
            continue
        taken.add(S.norm(name))
        out.append({"name": name, "description": " ".join(str(item.get("description", "")).split())})
        if len(out) == count:
            break
    return out


def add_viewpoint(location_aid: str, name: str, description: str) -> str:
    """Ajoute un point de vue à un lieu (sans image : elle se dessine ensuite, à partir de l'image du lieu)."""
    name = " ".join(str(name).split())
    if not name:
        raise ValueError("Donnez un nom au point de vue")
    with A.LOCK:
        data = A.load()
        loc = data["assets"].get(location_aid)
        if loc is None or loc["kind"] != "location" or loc.get("parent"):
            raise ValueError("Lieu inconnu")
        if any(a.get("parent") == location_aid and S.norm(a["name"]) == S.norm(name)
               for a in data["assets"].values()):
            raise ValueError("Ce lieu a déjà un point de vue de ce nom")
        aid, n = f"view_{_slug(name)}", 2
        base = aid
        while aid in data["assets"]:
            aid, n = f"{base}_{n}", n + 1
        A.add_asset(data, aid, "location", name, description.strip(), location_aid)
        A.save(data)
    return aid
