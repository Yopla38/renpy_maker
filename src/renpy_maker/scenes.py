"""Images de scène : découpage en plans, références, préparation, prompt proposé.

Une scène a une ou plusieurs images (« plans »). Chaque plan commence à une réplique
(from_line) et dure jusqu'au plan suivant. Un plan sans personnage explicite prend tous les
personnages de la scène. Les références d'un plan sont le décor, puis une image par personnage
(sa tenue dans la scène, à défaut son image de base). Toutes doivent être retenues.
"""

from __future__ import annotations

from renpy_maker import appsettings
import re

from renpy_maker import llm
from renpy_maker import prompts as PR
from renpy_maker import story as S
from renpy_maker.prompt_texts import t

MAX_REFS = 4  # images de référence de Klein (base comprise) : limite de l'API de BFL et du workflow ComfyUI

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
    # Un personnage cité dans « ce que l'on voit » est dans l'image, même s'il ne parle pas
    # (« Léa seule sur le quai, Tom arrive au loin »).
    note = (plan.get("shot") or {}).get("note", "")
    named = {c for c in sc.get("characters", []) if _names_in(c, note)}
    chosen = [c for c in sc.get("characters", []) if c in speakers or c in named]
    # Le même plan un instant plus tard (continuité, sans nouveau cadrage) : ceux qui étaient là y restent,
    # même s'ils ne parlent pas.
    if k > 0 and plan.get("continuity", True) and not _has_shot(plan):
        before = plan_characters(sc, sc["plans"][k - 1])
        chosen = [c for c in sc.get("characters", []) if c in chosen or c in before]
    return chosen or sc.get("characters", [])


def _names_in(name: str, text: str) -> bool:
    return bool(name) and bool(re.search(rf"(?<!\w){re.escape(name)}(?!\w)", text or "", re.IGNORECASE))


def split_ref(ref: str):
    from renpy_maker.assets import split_ref as _split
    return _split(ref)


def _previous_plan(sc: dict, plan: dict) -> dict | None:
    plans = sc.get("plans", [])
    k = next((i for i, p in enumerate(plans) if p is plan or p.get("id") == plan.get("id")), None)
    return plans[k - 1] if k else None


def _has_shot(plan: dict) -> bool:
    shot = plan.get("shot") or {}
    return bool(shot.get("framing") or shot.get("angle") or shot.get("note"))


def plan_refs(assets: dict, sc: dict, plan: dict) -> dict:
    """Images de référence d'un plan, dans l'ordre où Klein les reçoit (image 1, image 2…).

    Deux cas :
    - retouche (« edit ») : le plan suit l'image précédente (continuité) sans cadrage choisi. L'image précédente
      est l'image 1 (la base) ; le décor n'est pas repris (elle le montre déjà), ni les personnages qui y sont
      déjà ; seuls les personnages qui entrent dans l'image ajoutent leur référence ;
    - nouveau plan (« new ») : le décor, puis une image par personnage (sa tenue dans la scène, à défaut sa
      tenue par défaut ou son image de base), puis les images ajoutées, puis l'image précédente.

    Au plus MAX_REFS images : au-delà, les moins utiles sont écartées (dans l'ordre : image précédente d'un
    nouveau plan, images ajoutées, personnages qui ne parlent pas, décor) et le plan le signale (`notes`).
    Chaque référence automatique peut être décochée (plan["refs_exclude"]) ; `missing` liste ce qui bloque.
    """
    chars = {S.norm(a["name"]): k for k, a in assets.items() if a["kind"] == "character"}
    excluded = set(plan.get("refs_exclude", []))
    manual = plan.get("manual_refs", {})
    people = plan_characters(sc, plan)
    prev = _previous_plan(sc, plan)
    prev_people = plan_characters(sc, prev) if prev else []
    # Image de base d'une retouche : l'image précédente (continuité), sinon une image de scène ajoutée à la main.
    def usable(ref):
        aid, k = split_ref(ref)
        a = assets.get(aid)
        idx = k if k is not None else (a or {}).get("validated_candidate")
        return a is not None and aid != plan.get("asset") and idx is not None and idx < len(a.get("candidates", []))
    extras = plan.get("refs_extra", [])
    cont = plan.get("continuity_ref") if plan.get("continuity_ref") in extras else None
    if cont and not usable(cont):
        cont = None
    if cont is None:
        cont = next((r for r in extras if usable(r) and assets[split_ref(r)[0]].get("kind") == "scene"), None)
    mode = "edit" if cont and not _has_shot(plan) else "new"
    staying = [n for n in people if n in prev_people] if mode == "edit" else []
    speakers = {l["speaker"] for k, p in enumerate(sc.get("plans", []))
                if p is plan or p.get("id") == plan.get("id") for l in plan_lines(sc, k)}

    auto = []  # {id, key, label, ok, why, role, person} ; key = rôle stable (décor, tenue de X, personnage X)
    if sc.get("location"):
        lid = PR.match_asset(assets, {"kind": "location", "name": sc["location"], "parent_name": None}, chars)
        view = plan.get("viewpoint")  # point de vue choisi pour ce moment (sinon le lieu lui-même)
        if view and view in assets and assets[view].get("parent") == lid:
            lid = view
        auto.append({"id": lid, "key": "decor", "label": f"décor : {sc['location']}", "role": "decor",
                     "ok": bool(lid) and assets[lid]["status"] == "validated",
                     "why": f"décor « {sc['location']} » : image à retenir"})
    else:
        auto.append({"id": None, "key": None, "label": "", "ok": False, "why": "aucun lieu indiqué dans la scène"})

    for name in people:
        outfit = sc.get("outfits", {}).get(name)
        if outfit:
            oid = PR.match_asset(assets, {"kind": "outfit", "name": outfit, "parent_name": name}, chars)
            auto.append({"id": oid, "key": f"tenue:{S.norm(name)}", "label": f"{name} en tenue", "person": name,
                         "role": "person", "outfit": outfit, "ok": bool(oid) and assets[oid]["status"] == "validated",
                         "why": f"tenue « {outfit} » de {name} : image à retenir"})
        else:
            cid = chars.get(S.norm(name))
            # Sans tenue notée dans la scène : la tenue par défaut du personnage, sinon son image de base.
            dflt = (assets.get(cid) or {}).get("default_outfit") if cid else None
            outfit_name = None
            if dflt and dflt in assets and assets[dflt].get("validated_candidate") is not None:
                cid, outfit_name = dflt, assets[dflt].get("name")
            auto.append({"id": cid, "key": f"perso:{S.norm(name)}", "label": name, "person": name, "role": "person",
                         "outfit": outfit_name, "ok": bool(cid) and assets[cid]["status"] == "validated",
                         "why": f"{name} : image de personnage à retenir"})

    # Une tenue ajoutée à la main remplace la tenue automatique du même personnage : le choix manuel prime
    # sur la tenue notée dans la scène.
    overridden, extra_people = set(), {}
    for ref in plan.get("refs_extra", []):
        aid, _ = split_ref(ref)
        a = assets.get(aid)
        owner = ""
        if a and a.get("kind") == "outfit" and a.get("parent"):
            owner = assets.get(a["parent"], {}).get("name", "")
        elif a and a.get("kind") == "character":
            owner = a.get("name", "")
        if owner:  # l'image ajoutée d'une personne remplace sa référence automatique
            overridden.add(f"tenue:{S.norm(owner)}")
            overridden.add(f"perso:{S.norm(owner)}")
            extra_people[ref] = owner

    chosen, missing, notes, auto_out = [], [], [], []   # chosen : {ref, label, role, person, outfit, priority}
    for it in auto:
        if it["id"] is None:
            missing.append(it["why"])
            continue
        is_excluded = it["id"] in excluded or it.get("key") in excluded or it.get("key") in overridden
        if mode == "edit" and it["role"] == "decor" and manual.get("decor") is not False:
            is_excluded = True   # l'image précédente montre déjà le lieu
        if mode == "edit" and it.get("person") in staying and manual.get(it["key"]) is not False:
            is_excluded = True   # la personne est déjà dans l'image précédente
        auto_out.append({"id": it["id"], "key": it["key"], "label": it["label"], "excluded": is_excluded,
                         "ok": it["ok"], "why": it["why"]})
        if is_excluded:
            if (it.get("person") in people and it.get("person") not in staying and not plan.get("refs_extra")
                    and it.get("key") not in overridden):
                missing.append(f"{it['person']} est dans l'image mais sans image de référence : "
                               "recochez sa tenue ou retirez-le de l'image")
            continue
        if not it["ok"]:
            missing.append(it["why"])
            continue
        if it["role"] == "decor":
            priority = 2
        else:
            priority = 1 if it["person"] in speakers else 3
        chosen.append({"ref": it["id"], "label": it["label"], "role": it["role"], "person": it.get("person"),
                       "outfit": it.get("outfit"), "priority": priority})

    extra_out = []
    for ref in plan.get("refs_extra", []):
        aid, k = split_ref(ref)
        a = assets.get(aid)
        if a is None or aid == plan.get("asset"):
            continue
        name = a.get("name", aid) + (f" #{k}" if k is not None else "")
        extra_out.append({"id": ref, "label": name})
        idx = k if k is not None else a.get("validated_candidate")
        if idx is None or idx >= len(a.get("candidates", [])):
            missing.append(f"« {name} » ajoutée : image introuvable")
            continue
        if any(c["ref"] == ref for c in chosen):
            continue
        if ref == cont:
            chosen.append({"ref": ref, "label": f"{name} (ajoutée)", "role": "continuity", "person": None,
                           "outfit": None, "priority": 0 if mode == "edit" else 5})
        else:
            owner = extra_people.get(ref)
            chosen.append({"ref": ref, "label": f"{name} (ajoutée)", "role": "person" if owner else "extra",
                           "person": owner,
                           "outfit": a.get("name") if owner and a.get("kind") == "outfit" else None, "kind": a.get("kind"),
                           "priority": 1 if owner in speakers else (3 if owner else 4)})

    # Au plus MAX_REFS : on écarte d'abord les moins utiles (priorité la plus haute en dernier).
    keep = sorted(chosen, key=lambda c: c["priority"])[:MAX_REFS]
    for c in chosen:
        if c not in keep:
            notes.append(f"« {c['label']} » écartée : Klein reçoit {MAX_REFS} images au plus")
    # Ordre envoyé à Klein : l'image de base d'abord (image précédente en retouche, sinon le décor).
    rank = ({"continuity": 0, "person": 1, "decor": 2, "extra": 3} if mode == "edit"
            else {"decor": 0, "person": 1, "extra": 2, "continuity": 3})
    ordered = sorted(keep, key=lambda c: (rank[c["role"]], chosen.index(c)))

    entering = [n for n in people if n not in prev_people] if mode == "edit" else []
    leaving = [n for n in prev_people if n not in people] if mode == "edit" else []
    return {"refs": [c["ref"] for c in ordered], "labels": [c["label"] for c in ordered],
            "roles": [{k: c.get(k) for k in ("ref", "role", "person", "outfit", "kind")} for c in ordered],
            "mode": mode, "people": people, "staying": staying, "entering": entering, "leaving": leaving,
            "missing": missing, "notes": notes, "too_many": False, "auto": auto_out, "extra": extra_out}


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
    asset = assets.get(plan["asset"], {})
    if asset.get("status") != "validated" and not issues:
        issues.append("image de plan à retenir")
    return {"id": plan["id"], "from_line": plan["from_line"], "asset_id": plan["asset"],
            "characters": plan_characters(sc, plan), "refs": info["refs"], "labels": info["labels"],
            "auto": info["auto"], "extra": info["extra"], "shot": plan.get("shot", {}), "reused": False,
            "image_index": assets[plan["asset"]].get("validated_candidate"),
            "issues": issues, "ready": not issues, "notes": info["notes"], "mode": info["mode"],
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


def _person_index(info: dict, name: str) -> int | None:
    """Numéro de l'image qui montre cette personne : sa propre référence, sinon l'image précédente."""
    roles = info["roles"]
    own = next((i + 1 for i, r in enumerate(roles) if r["role"] == "person" and r["person"] == name), None)
    if own:
        return own
    return next((i + 1 for i, r in enumerate(roles) if r["role"] == "continuity"), None)


def _reference_line(assets: dict, n: int, r: dict) -> str:
    u = "scene_image.user."
    if r["role"] == "continuity":
        return t(u + "ref_previous", n=n)
    if r["role"] == "decor":
        return t(u + "ref_place", n=n, place=assets.get(r["ref"], {}).get("name", ""))
    if r["role"] == "person":
        who = PR.person_word(assets, r["person"])
        if r.get("outfit"):
            return t(u + "ref_person_outfit", n=n, name=r["person"], person=who, outfit=r["outfit"])
        return t(u + "ref_person", n=n, name=r["person"], person=who)
    aid, _ = split_ref(r["ref"])
    return t(u + "ref_other", n=n, name=assets.get(aid, {}).get("name", aid))


def build_request(st: dict, assets: dict, sc: dict, k: int) -> tuple[str, str]:
    """Demande de prompt pour FLUX.2 Klein (consigne et données), selon les règles de Klein : décrire ce qui se
    passe et ce qui change, nommer chaque image de référence par son numéro, ne jamais redécrire ce qu'elle
    montre. Deux cas (voir plan_refs) : retouche de l'image précédente, ou nouveau plan."""
    plan = sc["plans"][k]
    info = plan_refs(assets, sc, plan)
    edit = info["mode"] == "edit"
    system = t("scene_image.system_edit" if edit else "scene_image.system_new")
    u = "scene_image.user."
    shot = plan.get("shot") or {}
    lines = [t(u + "scene", title=sc["title"], summary=sc.get("summary", ""))]
    if info["refs"]:
        lines.append(t(u + "references"))
        lines += [_reference_line(assets, i + 1, r) for i, r in enumerate(info["roles"])]
    else:
        lines.append(t(u + "no_references", location=sc.get("location")))
    people = []
    for name in info["people"]:
        n = _person_index(info, name)
        who = PR.person_word(assets, name)
        if n is None:
            people.append(t(u + "person_without_reference", name=name, person=who))
        elif name in info["entering"]:
            people.append(t(u + "person_entering", name=name, person=who, n=n))
        else:
            people.append(t(u + "person", name=name, person=who, n=n))
    lines.append(t(u + "people", people="; ".join(people)))
    if info["leaving"]:
        lines.append(t(u + "leaving", people=", ".join(
            t(u + "person_leaving", name=n, person=PR.person_word(assets, n)) for n in info["leaving"])))
    if sc.get("decor"):
        lines.append(t(u + "decor", decor=", ".join(sc["decor"])))
    if not edit:
        if shot.get("framing") or shot.get("angle"):
            lines.append(t(u + "shot", framing=shot.get("framing"), angle=shot.get("angle")))
        else:
            lines.append(t(u + "shot_unset"))
        prev = sc["plans"][k - 1].get("shot") or {} if k > 0 else {}
        if prev.get("framing") or prev.get("angle"):
            lines.append(t(u + "previous_shot", framing=prev.get("framing", "?"), angle=prev.get("angle", "?")))
    if shot.get("note"):
        lines.append(t(u + "note", note=shot["note"]))
    # Seules les répliques des personnes visibles décrivent l'image : une réplique de quelqu'un absent du plan
    # ferait réapparaître cette personne dans le prompt.
    visible = set(info["people"]) | {S.NARRATOR}
    shown = [l for l in plan_lines(sc, k) if l["speaker"] in visible]
    expr = {}
    for line in shown:
        if line["speaker"] != S.NARRATOR and line.get("expression"):
            expr[line["speaker"]] = line["expression"]
    if expr:
        lines.append(t(u + "expressions", expressions=", ".join(
            t(u + "expression", name=n, expression=e) for n, e in expr.items())))
    lines.append(t(u + "dialogue"))
    lines += [t(u + "dialogue_line", name=l["speaker"], text=l["text"]) for l in shown] or [t(u + "no_dialogue")]
    return system, "\n".join(lines)


def suggest(st: dict, assets_data: dict, sc: dict, k: int, provider: str | None = None) -> str:
    system, user = build_request(st, assets_data["assets"], sc, k)
    provider = provider or appsettings.provider("text")
    return PR.with_style(PR.clean(llm.complete_task("prompt", system, user, provider)), PR.llm_style())




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
    k = "scene_image.detect.user."
    user = "\n".join([
        t(k + "scene", title=sc["title"], summary=sc["summary"]),
        t(k + "location", location=sc.get("location")),
        t(k + "places", places=str(known_places) if known_places else ""),
        t(k + "objects", objects=str(known_objects) if known_objects else ""),
        t(k + "declared", characters=", ".join(sc.get("characters", []))),
        t(k + "lines"),
    ] + [t(k + "line", speaker=l["speaker"], text=l["text"]) for l in sc.get("dialogue", [])])
    provider = provider or appsettings.provider("text")
    raw = llm.extract_json(llm.complete_task("prompt", t("scene_image.detect.system"), user, provider))
    out = []
    for el in raw.get("elements", []):
        name = str(el.get("name", "")).strip()
        kind = str(el.get("kind", "")).strip()
        if name and kind in ("location", "object", "character", "decor"):
            out.append({"name": name, "kind": kind, "description": str(el.get("description", "")).strip()})
    return out
