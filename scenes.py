"""Images de scène : découpage en plans, références, préparation, prompt proposé.

Une scène a une ou plusieurs images (« plans »). Chaque plan commence à une réplique
(from_line) et dure jusqu'au plan suivant. Un plan sans personnage explicite prend tous les
personnages de la scène. Les références d'un plan sont le décor, puis une image par personnage
(sa tenue dans la scène, à défaut son image de base). Toutes doivent être retenues.
"""

from __future__ import annotations

import re

import llm
import prompts as PR
import story as S

MAX_REFS = 5  # limite d'images de référence de Klein (décor compris)

# Valeurs de cadrage : clés en anglais (utilisées dans le prompt), libellés en français dans l'interface.
FRAMINGS = ["extreme close-up", "close-up", "medium close-up", "medium shot", "cowboy shot",
            "wide shot", "establishing shot"]
ANGLES = ["eye level", "low angle", "high angle", "from behind", "over the shoulder",
          "side profile", "bird's eye view"]


def plan_end(sc: dict, k: int) -> int:
    plans = sc["plans"]
    return plans[k + 1]["from_line"] if k + 1 < len(plans) else len(sc.get("dialogue", []))


def plan_lines(sc: dict, k: int) -> list[dict]:
    return sc.get("dialogue", [])[plans_start(sc, k): plan_end(sc, k)]


def plans_start(sc: dict, k: int) -> int:
    return sc["plans"][k]["from_line"]


def plan_characters(sc: dict, plan: dict) -> list[str]:
    """Personnages de l'image. Choix explicite de l'auteur, sinon ceux qui parlent dans ses répliques
    (une image ne montre pas quelqu'un qui n'a pas de place dans son passage). Sans locuteur, tous."""
    if plan.get("characters"):
        return plan["characters"]
    k = next((i for i, p in enumerate(sc.get("plans", [])) if p is plan or p.get("id") == plan.get("id")), None)
    if k is None:
        return sc.get("characters", [])
    speakers = {l["speaker"] for l in plan_lines(sc, k)}
    chosen = [c for c in sc.get("characters", []) if c in speakers]
    return chosen or sc.get("characters", [])


def split_ref(ref: str):
    from assets import split_ref as _split
    return _split(ref)


def plan_refs(assets: dict, sc: dict, plan: dict) -> dict:
    """Références d'un plan.

    Automatiques : décor et tenue (ou personnage) de chaque personnage du plan.
    Chacune peut être décochée (plan["refs_exclude"]). On peut ajouter n'importe quelle image
    retenue (plan["refs_extra"], par exemple l'image précédente pour la continuité).
    `missing` liste ce qui bloque : référence automatique non retenue, ajout non retenu.
    """
    chars = {S.norm(a["name"]): k for k, a in assets.items() if a["kind"] == "character"}
    excluded = set(plan.get("refs_exclude", []))
    auto = []  # {id, key, label, ok, why} ; key = rôle stable (décor, tenue de X, personnage X)

    if sc.get("location"):
        lid = PR.match_asset(assets, {"kind": "location", "name": sc["location"], "parent_name": None}, chars)
        auto.append({"id": lid, "key": "decor", "label": f"décor : {sc['location']}",
                     "ok": bool(lid) and assets[lid]["status"] == "validated",
                     "why": f"décor « {sc['location']} » : image à retenir"})
    else:
        auto.append({"id": None, "key": None, "label": "", "ok": False, "why": "aucun lieu indiqué dans la scène"})

    for name in plan_characters(sc, plan):
        outfit = sc.get("outfits", {}).get(name)
        if outfit:
            oid = PR.match_asset(assets, {"kind": "outfit", "name": outfit, "parent_name": name}, chars)
            auto.append({"id": oid, "key": f"tenue:{S.norm(name)}", "label": f"{name} en tenue", "person": name,
                         "ok": bool(oid) and assets[oid]["status"] == "validated",
                         "why": f"tenue « {outfit} » de {name} : image à retenir"})
        else:
            cid = chars.get(S.norm(name))
            auto.append({"id": cid, "key": f"perso:{S.norm(name)}", "label": name, "person": name,
                         "ok": bool(cid) and assets[cid]["status"] == "validated",
                         "why": f"{name} : image de personnage à retenir"})

    refs, labels, missing = [], [], []
    auto_out = []
    people = set(plan_characters(sc, plan))
    for it in auto:
        is_excluded = (it["id"] is not None and it["id"] in excluded) or (it.get("key") in excluded)
        if it["id"] is not None:
            auto_out.append({"id": it["id"], "key": it["key"], "label": it["label"], "excluded": is_excluded,
                             "ok": it["ok"], "why": it["why"]})
        if is_excluded:
            if it.get("person") in people and not plan.get("refs_extra"):
                missing.append(f"{it['person']} est dans l'image mais sans image de référence : "
                               "recochez sa tenue ou retirez-le de l'image")
            continue
        if it["ok"]:
            refs.append(it["id"])
            labels.append(it["label"])
        else:
            missing.append(it["why"])

    extra_out = []
    for ref in plan.get("refs_extra", []):
        aid, k = split_ref(ref)
        a = assets.get(aid)
        if a is None or aid == plan.get("asset"):
            continue
        name = a.get("name", aid) + (f" #{k}" if k is not None else "")
        extra_out.append({"id": ref, "label": name})
        idx = k if k is not None else a.get("validated_candidate")
        if idx is not None and idx < len(a.get("candidates", [])) and ref not in refs:
            refs.append(ref)
            labels.append(f"{name} (ajoutée)")
        else:
            missing.append(f"« {name} » ajoutée : image introuvable")

    return {"refs": refs, "labels": labels, "missing": missing, "too_many": len(refs) > MAX_REFS,
            "auto": auto_out, "extra": extra_out}


def is_placed(sc: dict, plan: dict, asset: dict, asset_id: str) -> bool:
    """Image placée (existante, choisie candidat par candidat) plutôt qu'image générée pour ce plan.
    Une image générée pour un plan a son propre nom (scene_<scène>_<plan>) et pas de candidat choisi."""
    own_name = asset_id.startswith(f"scene_{sc['id']}_{plan['id']}")
    return "candidate" in plan or asset.get("kind") != "scene" or not own_name


def plan_status(assets: dict, sc: dict, k: int) -> dict:
    plan = sc["plans"][k]
    if is_placed(sc, plan, assets.get(plan["asset"], {}), plan["asset"]):
        # image existante placée telle quelle : seule son état de retenue compte
        a = assets.get(plan["asset"], {})
        idx = plan.get("candidate", a.get("validated_candidate"))
        issues = [] if idx is not None and idx == a.get("validated_candidate") else ["image non retenue"]
        return {"id": plan["id"], "from_line": plan["from_line"], "asset_id": plan["asset"],
                "characters": [], "refs": [], "labels": [], "auto": [], "extra": [], "shot": {},
                "issues": issues, "ready": not issues, "reused": True, "image_index": idx,
                "asset_status": a.get("status"), "candidates": len(a.get("candidates", []))}
    info = plan_refs(assets, sc, plan)
    issues = list(info["missing"])
    if info["too_many"]:
        issues.append(f"{len(info['refs'])} références : Klein en accepte {MAX_REFS} au plus. "
                      "Retirez un personnage du plan ou scindez-le en deux plans.")
    asset = assets.get(plan["asset"], {})
    if asset.get("status") != "validated" and not issues:
        issues.append("image de plan à retenir")
    return {"id": plan["id"], "from_line": plan["from_line"], "asset_id": plan["asset"],
            "characters": plan_characters(sc, plan), "refs": info["refs"], "labels": info["labels"],
            "auto": info["auto"], "extra": info["extra"], "shot": plan.get("shot", {}), "reused": False,
            "image_index": assets[plan["asset"]].get("validated_candidate"),
            "issues": issues, "ready": not issues,
            "asset_status": asset.get("status"), "candidates": len(asset.get("candidates", []))}


def scene_status(st: dict, assets: dict) -> list[dict]:
    out = []
    for ch in st["chapters"]:
        for sc in ch["scenes"]:
            issues = []
            if not sc.get("dialogue"):
                issues.append("répliques à écrire")
            if not sc.get("plans"):
                issues.append("aucune image de scène")
            plans = [plan_status(assets, sc, k) for k in range(len(sc.get("plans", [])))]
            for p in plans:
                issues += [f"image {p['id']} : {x}" for x in p["issues"]]
            out.append({"chapter": ch["id"], "scene": sc["id"], "title": sc["title"],
                        "ready": not issues, "issues": issues, "plans": plans})
    return out


def _people_line(plan: dict, sc: dict, info: dict, assets: dict) -> str:
    """Qui est dans l'image (genre et âge, jamais le prénom), et de quelle image de référence on le tire."""
    labels = info["labels"]
    # Image de continuité : l'image du plan précédent (étiquette « · plan N »), qui montre les personnages.
    cont = next((i + 1 for i, lab in enumerate(labels) if lab.endswith("(ajoutée)") and " · plan " in lab), None)
    parts = []
    for name in plan_characters(sc, plan):
        plain = [lab.replace(" (ajoutée)", "") for lab in labels]
        idx = next((i + 1 for i, lab in enumerate(plain) if lab in (name, f"{name} en tenue")), None) or cont
        word = PR.person_word(assets, name)
        parts.append(f"{word} (image {idx})" if idx else f"{word} (no reference image)")
    return "People in this image : " + (", ".join(parts) if parts else "nobody") + "."


def build_request(st: dict, assets: dict, sc: dict, k: int) -> tuple[str, str]:
    """Prompt d'édition pour FLUX.2 Klein.

    Deux cas :
    - continuité (une image de référence ajoutée, par exemple la précédente, sans cadrage choisi) :
      c'est une RETOUCHE : même cadrage, même composition, seule l'action ou l'expression change ;
    - sinon : un nouveau plan. Le cadrage est alors explicite, et la composition est nouvelle.
    """
    plan = sc["plans"][k]
    info = plan_refs(assets, sc, plan)
    if info["refs"]:
        order = "; ".join(f"image {i + 1} = {PR.anonymize(lab, assets)}" for i, lab in enumerate(info["labels"]))
        refs_line = f"Reference images, by position: {order}."
    else:
        refs_line = "There are no reference images: describe the scene only."
    style = PR.llm_style()
    shot = plan.get("shot") or {}
    has_shot = bool(shot.get("framing") or shot.get("angle") or shot.get("note"))
    cont = next((i + 1 for i, lab in enumerate(info["labels"]) if lab.endswith("(ajoutée)")), None)
    edit_only = cont is not None and not has_shot

    if edit_only:
        rules = (
            f"This is an EDIT of image {cont}, not a new shot: keep its framing, camera angle, composition, "
            f"lighting and every person exactly as they are in image {cont}. Change only the expression and "
            "the action described in the dialogue below. Do not move the camera, do not zoom, do not change the place."
        )
    else:
        rules = (
            "Start with the camera: the framing, the distance, the angle, and what is in focus, as requested. "
            "The composition is new: never reuse the framing, camera position or layout of any reference image. "
            "References only give identity, outfit and the look of the place. "
            "Then say what stays identical to the references, in one short clause per person "
            "('Keep the woman from image 2 exactly as she is, with her outfit'). Do NOT re-describe their face, hair, body "
            "or clothes: the reference already shows them. "
            "Then state the changes: where each person stands in this framing, their pose, their expression "
            "(for example 'with a slight smile'), their action, and anything to add or remove. "
            "Lighting last. "
        )
    system = (
        "You write prompts for FLUX.2 Klein image editing, which composes or edits an image from reference images. "
        "Output ONLY the prompt, in English, one paragraph of 40 to 90 words, never more than 100. "
        f"{refs_line} "
        "Refer to every reference by its position ('the woman from image 2', 'the room from image 1'), "
        "and give each reference one role. Show only the people listed under 'People in this image', "
        "each one as the person of their numbered image: never swap two people, never add anyone else. "
        f"{rules}"
        "Use natural sentences, not tags. No negative terms, no quality words, no text in the image. "
        f"Keep one rendering style only and finish with these words, verbatim: {style}"
    )
    names = sc.get("characters", [])
    lines = [f"Scene : {sc['title']} — {PR.anonymize(sc['summary'], assets, names)}"]
    if sc.get("location"):
        lines.append(f"Location : {sc['location']}")
    lines.append(_people_line(plan, sc, info, assets))
    if sc.get("decor"):
        lines.append("Background details, scenery only (never a named person): " + ", ".join(sc["decor"]) + ".")
    if has_shot:
        lines.append(f"Requested shot : framing {shot.get('framing') or 'free'}, camera {shot.get('angle') or 'free'}"
                     + (f". Focus : {shot['note']}" if shot.get("note") else "") + ".")
    elif not edit_only:
        lines.append("Requested shot : not set. Choose a framing and camera angle different from the previous image.")
    if k > 0 and not edit_only:
        prev = sc["plans"][k - 1].get("shot") or {}
        if prev.get("framing") or prev.get("angle"):
            lines.append(f"Previous image shot : framing {prev.get('framing', '?')}, camera {prev.get('angle', '?')}. "
                         "Do not reuse its composition.")
    # Seules les répliques des personnages visibles décrivent l'image : une réplique de quelqu'un
    # absent du plan ferait réapparaître cette personne dans le prompt.
    visible = set(plan_characters(sc, plan)) | {S.NARRATOR}
    shown = [l for l in plan_lines(sc, k) if l["speaker"] in visible]
    def who(speaker: str) -> str:
        return speaker if speaker == S.NARRATOR else PR.person_word(assets, speaker)

    expr = {}
    for line in shown:
        expr[line["speaker"]] = line.get("expression", "neutre")
    if expr:
        lines.append("Expressions to show : " + ", ".join(f"{who(n)} : {e}" for n, e in expr.items()))
    lines.append("Dialogue in this image (French, for context) :")
    lines += [f"- {who(l['speaker'])} : {PR.anonymize(l['text'], assets, names)}" for l in shown] or ["- (aucune réplique)"]
    if info["refs"]:
        lines.append("Reference descriptions (context only, do not copy them word for word) :")
        for rid, lab in zip(info["refs"], [PR.anonymize(x, assets) for x in info["labels"]]):
            aid, k = split_ref(rid)
            if k is not None:
                # Image précise : Klein la voit ; le prompt de l'élément ne la décrit pas forcément.
                lines.append(f"- image {info['refs'].index(rid) + 1} ({lab})")
                continue
            src = assets.get(aid, {})
            text = src.get("prompt") or src.get("description", "")
            lines.append(f"- image {info['refs'].index(rid) + 1} ({lab}) : {PR.anonymize(text, assets)}")
    return system, "\n".join(lines)


def suggest(st: dict, assets_data: dict, sc: dict, k: int, provider: str | None = None) -> str:
    system, user = build_request(st, assets_data["assets"], sc, k)
    provider = provider or st["settings"]["providers"]["text"]
    return PR.with_style(PR.clean(llm.complete(provider, system, user)), PR.llm_style())


DETECT_SYSTEM = """You list the visual elements that a scene needs to be drawn.
Output ONLY a JSON object: {"elements": [{"name": "...", "kind": "location" | "object" | "character" | "decor", "description": "..."}]}.
- Write names and descriptions in French, as they appear in the story. Keep names short and specific.
- kind "location": a place or part of a place (the yard, the barn, the road).
- kind "object": a prop or a vehicle that matters visually and is named in the story.
- kind "character": a NAMED individual of the story, or a person with a role who speaks or acts in the scene and is
  NOT in the declared characters list (for example "le père d'Eve"). Name them as the story does.
- kind "decor": background of the scene, not story people: a crowd, dancing couples, villagers in the background,
  ambient details (lanterns, fireworks, cows in a field). These are part of the image, never characters.
- Do not list clothes. Do not list small consumables (food, drinks) or things only mentioned abstractly.
- At most 8 elements."""


_STOP = {"de", "la", "le", "les", "l", "du", "des", "d", "en", "au", "aux", "a", "et", "devant",
         "pres", "entree", "dehors", "exterieur", "interieur", "the", "of"}


def _tokens(text: str) -> set[str]:
    import unicodedata
    plain = unicodedata.normalize("NFKD", text.lower()).encode("ascii", "ignore").decode()
    words = re.findall(r"[a-z0-9]+", plain)
    return {w for w in words if w not in _STOP and len(w) > 1}


def match_registry(name: str, kind: str, assets: dict) -> str | None:
    """Trouve l'élément du registre qui désigne le même lieu ou objet, malgré les variantes de nom.

    Règle : tous les mots significatifs de l'un sont dans l'autre (« Cour de la ferme » ⊂
    « Cour de la ferme, devant l'étable »). Si plusieurs conviennent, le plus court gagne.
    """
    want = _tokens(name)
    if not want:
        return None
    best = None
    for aid, a in assets.items():
        if a["kind"] != kind:
            continue
        have = _tokens(a.get("name", aid))
        if have and (want <= have or have <= want):
            if best is None or len(a.get("name", "")) < len(assets[best].get("name", "")):
                best = aid
    return best


def detect_elements(st: dict, sc: dict, assets: dict, provider: str | None = None) -> list[dict]:
    """Relève les lieux, objets et véhicules visibles dans la scène (sans toucher au registre)."""
    known_places = [a.get("name", k) for k, a in assets.items() if a["kind"] == "location"]
    known_objects = [a.get("name", k) for k, a in assets.items() if a["kind"] == "object"]
    declared = ", ".join(sc.get("characters", [])) or "(aucun)"
    user = "\n".join([
        f"Scène : {sc['title']} — {sc['summary']}",
        f"Lieu indiqué : {sc.get('location') or '(aucun)'}",
        f"Lieux déjà connus (réutiliser exactement ce nom si c'est le même lieu) : {known_places or '(aucun)'}",
        f"Objets déjà connus (idem) : {known_objects or '(aucun)'}",
        f"Personnages déclarés dans la scène : {declared}",
        "Répliques :",
    ] + [f"- {l['speaker']} : {l['text']}" for l in sc.get("dialogue", [])])
    provider = provider or st["settings"]["providers"]["text"]
    raw = llm.extract_json(llm.complete(provider, DETECT_SYSTEM, user))
    out = []
    for el in raw.get("elements", []):
        name = str(el.get("name", "")).strip()
        kind = str(el.get("kind", "")).strip()
        if name and kind in ("location", "object", "character", "decor"):
            out.append({"name": name, "kind": kind, "description": str(el.get("description", "")).strip()})
    return out
