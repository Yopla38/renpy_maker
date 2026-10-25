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

PERSON_DESCRIPTOR_HINT = ("descriptor : en anglais, le genre et la tranche d'âge (« young woman », « adult man », "
                          "« teenage boy »). Ne devine pas : si le texte ne le dit pas, laisse-le vide.")


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
    system = ("Tu proposes des personnages pour un roman visuel. Réponds uniquement par du JSON : "
              '{"characters": [{"name": "...", "description": "...", "descriptor": "..."}]}. '
              "name : un prénom ou un nom court, en français. description : en français, une ou deux phrases "
              "sur l'apparence et le rôle. " + PERSON_DESCRIPTOR_HINT)
    user = (f"Histoire : {idea}\nPersonnages déjà retenus (ne les répète pas) : {', '.join(existing) or 'aucun'}\n"
            f"Propose {count} personnages.")
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
    system = ("Tu proposes un lieu pour une scène de roman visuel. Réponds uniquement par du JSON : "
              '{"name": "...", "description": "..."}. name : court, en français (« Le compartiment du train »). '
              "description : une ou deux phrases sur le décor seulement, sans personnage.")
    before = context or "(début de l'histoire)"
    user = (f"Histoire : {idea}\nLieux déjà utilisés : {', '.join(existing) or 'aucun'}\n"
            f"Ce qui vient de se passer : {before}")
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
    history = "\n".join(f"{l['speaker']} : {l['text']}" for l in recent) or "(la scène commence)"
    system = ("Tu écris une seule réplique pour un roman visuel, en français. Réponds uniquement par du JSON : "
              '{"speaker": "...", "text": "..."}. speaker : exactement un de ces noms : '
              f"{', '.join(speakers)}. text : une à deux phrases, naturelles, sans didascalie.")
    user = (f"Histoire : {st.get('idea') or st.get('synopsis') or ''}\n"
            f"Scène : {sc.get('title', '')} — {sc.get('summary', '')}\n"
            f"Lieu : {sc.get('location') or 'non précisé'}\n"
            f"Personnages présents : {', '.join(present) or 'aucun'}\n"
            f"Répliques déjà écrites :\n{history}\n"
            "Écris la réplique qui suit.")
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
                                       "characters": present if speaker == S.NARRATOR else [speaker],
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
    system = ("Tu proposes des tenues (vêtements) pour un personnage de roman visuel. Réponds uniquement par du "
              'JSON : {"outfits": [{"name": "...", "description": "..."}]}. name : court, en français '
              "(« Robe du soir »). description : une phrase sur les vêtements seulement (matière, couleur, coupe). "
              "Pas de nudité, pas de sous-vêtement. Ne répète pas les tenues déjà présentes.")
    user = (f"Histoire : {idea}\nPersonnage : {character}\nApparence : {description or '(non précisée)'}\n"
            f"Tenues déjà présentes : {', '.join(existing) or 'aucune'}\nPropose {count} tenues.")
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
