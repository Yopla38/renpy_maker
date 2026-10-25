"""Personnages, lieux, tenues : identité, références, LoRA, dessin."""

from __future__ import annotations

import appsettings
import re
import uuid

import assets as A
import llm
import prompts as PR
import scenes as SC
import story as S
from facile_base import _aid, _same, _slug, _url
from facile_jobs import _check_cancel, _progress, _say, _start, _submit


def _refs_for(assets: dict, aid: str) -> list[str]:
    """Images de référence d'une carte, dans l'ordre du prompt. Une tenue s'appuie toujours sur son personnage."""
    a = assets[aid]
    if a["kind"] == "outfit":
        parent = assets.get(a.get("parent") or "")
        if parent and parent.get("image_stale"):
            raise ValueError(f"Redessinez d'abord « {parent['name']} » : son image date d'avant la modification "
                             "de son genre ou de son apparence.")
        if not parent or parent.get("validated_candidate") is None:
            raise ValueError(f"Dessinez d'abord le personnage « {parent['name'] if parent else '?'} » : "
                             "sa tenue s'appuie sur son image.")
    return PR.ref_order(assets, aid)

def set_element_refs(aid: str, refs: list, based_on: str | None = None) -> dict:
    """Images de référence choisies pour un personnage, une tenue ou un lieu, et tenue de départ d'une tenue."""
    with A.LOCK:
        data = A.load()
    a = data["assets"].get(aid)
    if a is None or a["kind"] not in ("character", "outfit", "location"):
        raise ValueError("Élément inconnu")
    chosen = []
    for rid in refs:
        if rid == aid:
            continue
        if not PR._retained(data["assets"], rid):
            raise ValueError("Cette image n'est pas encore retenue : elle ne peut pas servir de référence.")
        if rid not in chosen:
            chosen.append(rid)
    if based_on:
        base = data["assets"].get(based_on)
        if (a["kind"] != "outfit" or based_on == aid or base is None or base.get("kind") != "outfit"
                or base.get("parent") != a.get("parent") or not PR._retained(data["assets"], based_on)):
            raise ValueError("La tenue de départ doit être une autre tenue retenue du même personnage.")
    previous = a.get("based_on") or None
    a["refs"] = chosen
    a["based_on"] = based_on or None
    if (a["based_on"] or None) != previous:
        a["prompt"] = ""  # la consigne de la tenue dépend de sa tenue de départ : on la réécrit
    with A.LOCK:
        A.save(data)
    return {"ok": True}

def _rekey(key: str, old: str, new: str) -> str:
    """Clé de référence (« tenue:nom », « perso:nom ») après un renommage de personnage."""
    if ":" not in key:
        return key
    role, name = key.split(":", 1)
    return f"{role}:{S.norm(new)}" if name == S.norm(old) else key

def _rename_character(st: dict, old: str, new: str) -> None:
    """Renommage d'un personnage partout dans l'histoire : scènes, tenues, répliques, découpages."""
    for sc in S.all_scenes(st):
        sc["characters"] = [new if _same(c, old) else c for c in sc.get("characters", [])]
        sc["outfits"] = {(new if _same(k, old) else k): v for k, v in sc.get("outfits", {}).items()}
        for line in sc.get("dialogue", []):
            if _same(line.get("speaker", ""), old):
                line["speaker"] = new
        for plan in sc.get("plans", []):
            if plan.get("characters"):
                plan["characters"] = [new if _same(c, old) else c for c in plan["characters"]]
            for field in ("refs_exclude", "continuity_excluded"):
                if plan.get(field):
                    plan[field] = [_rekey(k, old, new) for k in plan[field]]
            if plan.get("manual_refs"):
                plan["manual_refs"] = {_rekey(k, old, new): v for k, v in plan["manual_refs"].items()}

def _rename_outfit(st: dict, character: str, old: str, new: str) -> None:
    """Renommage d'une tenue : le texte de la scène qui la porte suit."""
    for sc in S.all_scenes(st):
        sc["outfits"] = {k: (new if _same(k, character) and _same(v, old) else v)
                         for k, v in sc.get("outfits", {}).items()}

def update_element(aid: str, name: str | None = None, description: str | None = None,
                   descriptor: str | None = None) -> dict:
    """Designer, onglet Identité : nom, description, genre et âge (personnage ou tenue)."""
    with S.LOCK:
        st = S.load()
    with A.LOCK:
        data = A.load()
    a = data["assets"].get(aid)
    if a is None:
        raise ValueError("Élément inconnu")
    if a["kind"] not in ("character", "outfit"):
        raise ValueError("Seuls les personnages et les tenues se modifient ici")
    old = a["name"]
    new = old if name is None else name.strip()
    if not new:
        raise ValueError("Le nom ne peut pas être vide")
    if a["kind"] == "character":
        if not _same(new, old):
            if any(_same(o["name"], new) for k, o in data["assets"].items() if o["kind"] == "character" and k != aid):
                raise ValueError("Un autre personnage porte déjà ce nom")
            _rename_character(st, old, new)
    else:
        parent = data["assets"].get(a.get("parent") or "")
        if parent is None:
            raise ValueError("Cette tenue n'est rattachée à aucun personnage")
        if not _same(new, old):
            if any(_same(o["name"], new) for k, o in data["assets"].items()
                   if o["kind"] == "outfit" and o.get("parent") == a.get("parent") and k != aid):
                raise ValueError("Ce personnage a déjà une tenue de ce nom")
            _rename_outfit(st, parent["name"], old, new)
    changed = not _same(new, old)
    identity = False  # genre ou apparence : l'image du personnage ne correspond plus
    a["name"] = new
    if description is not None and description.strip() != a.get("description", ""):
        a["description"] = description.strip()
        changed = identity = True
    if descriptor is not None and a["kind"] == "character":
        value = descriptor.strip()
        if value and not PR.valid_descriptor(value):
            raise ValueError("Le genre et l'âge doivent contenir un mot de genre (woman, man, girl, boy…)")
        if value != (a.get("descriptor") or ""):
            changed = identity = True
        if value:
            a["descriptor"] = value
        else:
            a.pop("descriptor", None)
    if identity and a["kind"] == "character" and a.get("validated_candidate") is not None:
        a["image_stale"] = True
    if changed:
        a["prompt"] = ""  # le prompt sera rédigé de nouveau à partir de la description modifiée
    with A.LOCK:
        A.save(data)
    with S.LOCK:
        S.save(st)
    return {"ok": True, "name": new}

def set_character_mode(mode: str) -> dict:
    """Comment créer les personnages : « auto » (dessinés à l'arrivée) ou « designer » (validés un par un)."""
    if mode not in ("auto", "designer"):
        raise ValueError("Mode inconnu")
    with S.LOCK:
        st = S.load()
        st["settings"]["character_mode"] = mode
        S.save(st)
    return {"ok": True, "mode": mode}

def suggest_identity(aid: str) -> dict:
    """Pré-remplit la description, et le genre et l'âge, d'un personnage à partir de l'histoire,
    de ses scènes et de ses répliques (c'est là que le rôle et le genre se voient)."""
    with A.LOCK:
        data = A.load()
    char = data["assets"].get(aid)
    if char is None or char["kind"] != "character":
        raise ValueError("Personnage inconnu")
    with S.LOCK:
        st = S.load()
    name = char["name"]
    scenes = [sc for sc in S.all_scenes(st) if any(_same(c, name) for c in sc.get("characters", []))]
    story = " ".join(x for x in (st.get("idea"), st.get("synopsis")) if x)
    context = "\n".join(f"- {sc['title']} : {sc.get('summary', '')}" for sc in scenes)
    lines = [f"{l['speaker']} : {l['text']}" for sc in scenes for l in sc.get("dialogue", [])
             if _same(l.get("speaker", ""), name)][:8]
    system = ("Tu décris un personnage de roman visuel à partir de l'histoire et de ses répliques. "
              "Réponds uniquement par du JSON : {\"description\": \"...\", \"descriptor\": \"...\"}. "
              "description : en français, une ou deux phrases sur l'apparence (cheveux, yeux, silhouette, style), "
              "seulement ce que l'histoire indique. "
              "descriptor : en anglais, le genre et la tranche d'âge (« young woman », « adult man », « teenage boy »). "
              "Ne devine jamais le genre : ni le rôle, ni le prénom, ni le genre de l'héroïne ne suffisent. "
              "Si le texte ne l'indique pas clairement (pronoms, « monsieur », « madame », accords), "
              "laisse descriptor vide.")
    user = (f"Personnage : {name}\nHistoire : {story or '(non précisée)'}\n"
            f"Scènes où il apparaît :\n{context or '(aucune)'}\n"
            f"Ses répliques :\n" + ("\n".join(lines) or "(aucune)"))
    raw = llm.extract_json(llm.complete_task("prompt", system, user, appsettings.provider("text")))
    description = " ".join(str(raw.get("description", "")).split()) if isinstance(raw, dict) else ""
    descriptor = str(raw.get("descriptor", "")).strip().lower() if isinstance(raw, dict) else ""
    return {"description": description, "descriptor": descriptor if PR.valid_descriptor(descriptor) else ""}

def create_outfit(character_aid: str, name: str, description: str, scene_ids: list[str]) -> dict:
    """Designer, atelier : crée une tenue pour un personnage et la porte dans les scènes choisies."""
    if not name.strip():
        raise ValueError("Donnez un nom à la tenue")
    with A.LOCK:
        data = A.load()
    char = data["assets"].get(character_aid)
    if char is None or char["kind"] != "character":
        raise ValueError("Personnage inconnu")
    if any(o["kind"] == "outfit" and o.get("parent") == character_aid and _same(o["name"], name)
           for o in data["assets"].values()):
        raise ValueError("Ce personnage a déjà une tenue de ce nom")
    new_id = f"outfit_{_slug(name)}_{uuid.uuid4().hex[:6]}"
    A.add_asset(data, new_id, "outfit", name.strip(), description.strip(), character_aid)
    with A.LOCK:
        A.save(data)
    with S.LOCK:
        st = S.load()
        for sc in S.all_scenes(st):
            if sc["id"] in scene_ids and any(_same(c, char["name"]) for c in sc.get("characters", [])):
                for key in [k for k in sc.get("outfits", {}) if _same(k, char["name"])]:
                    sc["outfits"].pop(key)
                sc.setdefault("outfits", {})[char["name"]] = name.strip()
        S.save(st)
    return {"aid": new_id, "name": name.strip()}

def _element_card(assets: dict, kind: str, name: str, parent: str | None = None) -> dict:
    aid = _aid(assets, kind, name, parent)
    a = assets.get(aid) if aid else None
    idx = a.get("validated_candidate") if a else None
    blocked = False
    if a and kind == "outfit":
        blocked = assets.get(a.get("parent") or "", {}).get("validated_candidate") is None
    return {"name": name, "aid": aid, "image": _url(a, idx) if a else None, "ready": idx is not None,
            "description": a.get("description", "") if a else "",
            "descriptor": a.get("descriptor", "") if a else "",
            "prompt": a.get("prompt", "") if a else "", "blocked": blocked, "parent": parent or "",
            "loras": list(a.get("loras", [])) if a else [],
            "refs": list(a.get("refs", [])) if a else [], "based_on": (a.get("based_on") or "") if a else ""}

def _ensure_descriptors(st: dict) -> None:
    """Genre et âge de chaque personnage, pour les prompts (complète les anciennes histoires)."""
    with A.LOCK:
        data = A.load()
    missing = [k for k, a in data["assets"].items()
               if a["kind"] == "character" and not PR.valid_descriptor(a.get("descriptor"))]
    if not missing:
        return
    found = {k: PR.describe_person(st, data["assets"][k]["name"], data["assets"][k].get("description", ""))
             for k in missing}
    with A.LOCK:
        data = A.load()
        for k, word in found.items():
            if word:  # un descriptif invalide reste absent : il sera redemandé
                data["assets"][k]["descriptor"] = word
        A.save(data)

def set_asset_loras(aid: str, loras: list[dict]) -> dict:
    """LoRA ajoutés à une image (réglage fin). Utilisés seulement quand le moteur est ComfyUI."""
    clean = []
    for item in loras:
        name = str(item.get("name", "")).strip()
        if not name:
            continue
        strength = float(item.get("strength", 1.0))
        if not -2.0 <= strength <= 2.0:
            raise ValueError("La force d'un LoRA doit être entre -2 et 2")
        clean.append({"name": name, "strength": strength, "clip": bool(item.get("clip", False))})
    with A.LOCK:
        data = A.load()
        if aid not in data["assets"]:
            raise ValueError("Élément inconnu")
        data["assets"][aid]["loras"] = clean
        A.save(data)
    return {"ok": True, "loras": clean}

def redo_card(aid: str, prompt: str | None = None) -> dict:
    with A.LOCK:
        assets = A.load()["assets"]
    if aid not in assets:
        raise ValueError("Élément inconnu")
    _refs_for(assets, aid)  # refuse tout de suite une tenue sans image de son personnage
    if prompt is not None and not prompt.strip():
        raise ValueError("Le prompt est vide")
    return _start("Image", _card_work, aid, prompt)

def _wrong_person(text: str, assets: dict, aid: str) -> bool:
    """Un prompt de tenue qui parle d'une autre personne que le personnage (« woman » pour un homme,
    « she » ou « her »…) ne doit pas servir : il a été écrit avant la correction du genre."""
    parent = assets.get(assets[aid].get("parent") or "")
    if not parent:
        return False
    noun = PR.person_noun(parent.get("descriptor"))
    if noun == "person":
        return False
    low = text.lower()
    others = [w for w in ("woman", "man", "girl", "boy") if w != noun]
    if any(re.search(rf"\b{w}\b", low) for w in others):
        return True
    return noun in ("man", "boy") and bool(re.search(r"\b(she|her)\b", low))

def _card_work(job_id: str, aid: str, prompt: str | None = None) -> None:
    with S.LOCK:
        _ensure_descriptors(S.load())
    with A.LOCK:
        data = A.load()
    a = data["assets"][aid]
    refs = _refs_for(data["assets"], aid)
    if not prompt:
        prompt = a.get("prompt")
    if prompt and a["kind"] == "outfit" and _wrong_person(prompt, data["assets"], aid):
        _say(job_id, "Le prompt visait une autre personne : nouvelle rédaction…")
        prompt = None
    if not prompt:
        _say(job_id, f"Description de « {a['name']} »…")
        with S.LOCK:
            st = S.load()
        prompt = PR.suggest(st, data, aid)
    prompt = prompt.strip()
    with A.LOCK:
        data = A.load()
        data["assets"][aid]["prompt"] = prompt
        A.save(data)
    _say(job_id, f"Dessin de « {a['name']} » (une à deux minutes)…")
    _check_cancel(job_id)
    idx = A.generate_candidate(aid, refs, prompt, None, "replicate", None, on_progress=_progress(job_id),
                               on_submit=_submit(job_id))
    with A.LOCK:
        data = A.load()
        A.set_status(data, aid, idx, True)
        data["assets"][aid].pop("image_stale", None)
        A.save(data)

def suggest_prompt(kind: str, target: str) -> dict:
    """Propose un nouveau prompt (en anglais) pour une carte ou un plan. Ne l'enregistre pas."""
    with S.LOCK:
        st = S.load()
    _ensure_descriptors(st)
    if kind == "card":
        with A.LOCK:
            data = A.load()
        if target not in data["assets"]:
            raise ValueError("Élément inconnu")
        return {"prompt": PR.suggest(st, data, target)}
    if kind == "plan":
        for sc in S.all_scenes(st):
            for k, plan in enumerate(sc.get("plans", [])):
                if plan["asset"] == target:
                    with A.LOCK:
                        data = A.load()
                    return {"prompt": SC.suggest(st, data, sc, k)}
        raise ValueError("Plan inconnu")
    raise ValueError("Type inconnu")
