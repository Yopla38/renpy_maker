"""Plans : découpage des scènes, répliques, images, continuité."""

from __future__ import annotations

import hashlib
import shutil
import uuid

from renpy_maker import appsettings
from renpy_maker import assets as A
from renpy_maker import llm
from renpy_maker import paths
from renpy_maker import renpy_export as RE
from renpy_maker import scenes as SC
from renpy_maker.prompt_texts import t
from renpy_maker import story as S
from renpy_maker.facile_base import (
    _characters,
    _find_plan,
    _find_scene,
    _locations,
    _outfits,
    _proposal_cap,
    _url,
    shot_characters,
)
from renpy_maker.facile_elements import _ensure_descriptors
from renpy_maker.facile_jobs import _check_cancel, _progress, _say, _start, _submit


def _text_hash(text: str) -> str:
    return hashlib.sha1((text or "").encode("utf-8")).hexdigest()[:16]

def _changes_outfit(plan: dict) -> bool:
    """Décision mise en cache pour le texte actuel du plan (vrai seulement si elle est à jour)."""
    cached = plan.get("outfit_change") or {}
    note = (plan.get("shot") or {}).get("note", "")
    return bool(cached.get("change")) and cached.get("hash") == _text_hash(note)

def _ask_outfit_change(st: dict, sc: dict, text: str) -> bool | None:
    """Le modèle répond : le texte décrit-il un changement de vêtement ou d'apparence ? None si pas de réponse claire."""
    system = t("outfit_change.system")
    user = t("outfit_change.user", characters=", ".join(sc.get("characters", [])), text=text)
    try:
        raw = llm.extract_json(llm.complete_task("decision", system, user, appsettings.provider("text")))
    except (llm.LLMError, ValueError):
        return None
    value = raw.get("change") if isinstance(raw, dict) else None
    return value if isinstance(value, bool) else None

def refresh_outfit_decisions(st: dict, sc: dict, plans: list[dict]) -> None:
    """Met à jour la décision de chaque plan dont le texte a changé. Appelé hors des verrous (appel réseau)."""
    for plan in plans:
        text = (plan.get("shot") or {}).get("note", "")
        digest = _text_hash(text)
        if (plan.get("outfit_change") or {}).get("hash") == digest:
            continue
        value = False if not text.strip() else _ask_outfit_change(st, sc, text)
        if value is not None:
            plan["outfit_change"] = {"hash": digest, "change": value}

def _merge_outfit_decisions(sc: dict, decisions: dict) -> bool:
    """Reporte sur le découpage enregistré les décisions de tenue prises sur un instantané, seulement
    pour les plans dont le texte n'a pas changé entre-temps. Renvoie True si quelque chose a changé."""
    changed = False
    for plan in sc.get("plans", []):
        dec = decisions.get(plan["id"])
        if not dec or plan.get("outfit_change") == dec:
            continue
        if dec.get("hash") == _text_hash((plan.get("shot") or {}).get("note", "")):
            plan["outfit_change"] = dec
            changed = True
    return changed

def apply_continuity(sc: dict, assets: dict) -> bool:
    """Continuité : à partir du deuxième plan, l'image du plan précédent est une référence (état réel des
    personnages). Sauf si le texte du plan décrit un changement de tenue, la tenue de référence des
    personnages présents dans les deux plans est alors mise de côté.
    Les choix faits à la main (plan["manual_refs"]) ne sont jamais modifiés. Renvoie True si le découpage a changé."""
    changed = False
    prev = None
    for plan in sc.get("plans", []):
        prev_ok = prev is not None and assets.get(prev["asset"], {}).get("validated_candidate") is not None
        use = bool(plan.get("continuity", True)) and prev_ok
        want_ref = prev["asset"] if use else None
        if plan.get("continuity_ref") != want_ref:
            extra = [r for r in plan.get("refs_extra", []) if r != plan.get("continuity_ref")]
            if want_ref and want_ref not in extra:
                extra.append(want_ref)
            plan["refs_extra"] = extra
            plan["continuity_ref"] = want_ref
            changed = True
        manual = plan.get("manual_refs", {})
        want_excl = []
        if use and not _changes_outfit(plan):
            shared = set(SC.plan_characters(sc, prev)) & set(SC.plan_characters(sc, plan))
            want_excl = [f"tenue:{S.norm(n)}" for n in sorted(shared) if n in sc.get("outfits", {})]
        old_excl = plan.get("continuity_excluded", [])
        want_excl = [k for k in want_excl if k not in manual]
        if sorted(old_excl) != sorted(want_excl):
            # les exclusions choisies à la main restent telles quelles
            excl = [k for k in plan.get("refs_exclude", []) if k not in old_excl or k in manual]
            plan["refs_exclude"] = excl + [k for k in want_excl if k not in excl]
            plan["continuity_excluded"] = want_excl
            changed = True
        prev = plan
    return changed

def _refs_view(sc: dict, plan: dict, assets: dict) -> dict:
    """Images de référence d'un plan : celles du moteur (décor, personnages, tenues) et celles ajoutées."""
    info = SC.plan_refs(assets, sc, plan)
    auto = []
    for it in info["auto"]:
        a = assets.get(it["id"], {})
        auto.append({"key": it["key"], "label": it["label"], "excluded": it["excluded"], "ok": it["ok"],
                     "image": _url(a, a.get("validated_candidate")) if a else None})
    extra_items = []
    for e in info["extra"]:
        aid, k = SC.split_ref(e["id"])
        a = assets.get(aid, {})
        idx = k if k is not None else a.get("validated_candidate")
        extra_items.append({"ref": e["id"], "label": e["label"], "image": _url(a, idx) if a else None,
                            "continuity": e["id"] == plan.get("continuity_ref")})
    return {"auto": auto, "extra": [e["id"] for e in info["extra"]], "extra_items": extra_items,
            "missing": info["missing"], "notes": info["notes"], "mode": info["mode"], "order": info["labels"]}

def _plan_view(sc: dict, plan: dict, assets: dict) -> dict:
    a = assets.get(plan["asset"], {})
    refs = _refs_view(sc, plan, assets)
    # Les LoRA ne s'appliquent qu'avec ComfyUI : le rôle (base ou edit) dépend des références du plan.
    used = refs["extra"] or any(not r["excluded"] for r in refs["auto"])
    return {"id": plan["id"], "aid": plan["asset"], "from_line": plan["from_line"], "pause": bool(plan.get("pause")),
            "speaker": plan.get("speaker", ""), "speech": plan.get("speech", ""),
            "viewpoint": plan.get("viewpoint", "") or "",
            "candidate": RE.plan_index(plan, a) if a else None,
            "loras": list(a.get("loras", [])) if a else [],
            "comfy": appsettings.image_for("edit" if used else "base")["engine"] == "comfyui",
            "refs": refs,
            "continuity": bool(plan.get("continuity", True)),
            "characters": SC.plan_characters(sc, plan),
            "text": (plan.get("shot") or {}).get("note", ""),
            "image": _url(a, RE.plan_index(plan, a)) if a else None,
            "prompt": a.get("prompt", "")}

def _default_tags(sc: dict, line: int) -> dict:
    """Bulles présélectionnées : la personne qui parle (si c'est un personnage de la scène), le lieu de la
    scène, et la tenue que la scène prévoit pour elle."""
    speaker = sc["dialogue"][line].get("speaker", "")
    present = [speaker] if speaker in sc.get("characters", []) else []
    outfits = {c: sc["outfits"][c] for c in present if sc.get("outfits", {}).get(c)}
    return {"characters": present, "location": sc.get("location", ""), "outfits": outfits}

def _effective_tags(sc: dict, line: int) -> dict:
    """Les bulles telles qu'elles sont affichées : le choix enregistré, ou le défaut."""
    stored = (sc.get("line_tags") or {}).get(str(line))
    return stored if stored is not None else _default_tags(sc, line)

def update_line(sid: str, line: int, speaker: str, text: str) -> dict:
    """Corrige une réplique déjà écrite : qui parle, et ce qui est dit. Les bulles et les plans restent."""
    with S.LOCK:
        st = S.load()
        sc = _find_scene(st, sid)
        dialogue = sc.get("dialogue", [])
        if not 0 <= line < len(dialogue):
            raise ValueError("Réplique inconnue")
        speaker = speaker.strip()
        if speaker != "Narration" and speaker not in sc.get("characters", []):
            raise ValueError("La personne qui parle doit être un personnage de la scène, ou la narration")
        text = text.strip()
        if not text:
            raise ValueError("Une réplique ne peut pas être vide")
        dialogue[line]["speaker"] = speaker
        dialogue[line]["text"] = text
        S.save(st)
    return {"ok": True}

def set_line_tags(sid: str, line: int, characters: list, location: str, outfits: dict) -> dict:
    """Bulles d'une réplique : qui est présent, dans quel lieu, et en quelle tenue. Choisies par l'auteur,
    elles sont données au découpage et décident des personnages de chaque plan."""
    with S.LOCK:
        st = S.load()
        sc = _find_scene(st, sid)
        if not 0 <= line < len(sc.get("dialogue", [])):
            raise ValueError("Réplique inconnue")
        known = set(_characters(st))
        if any(c not in known for c in characters):
            raise ValueError("Personnage inconnu")
        if location and location not in set(_locations(st)):
            raise ValueError("Lieu inconnu")
        allowed = {(c, o) for c, o in _outfits(st)}
        for c, o in outfits.items():
            if c not in characters or (c, o) not in allowed:
                raise ValueError("Cette tenue ne correspond pas à un personnage présent dans la réplique")
        for c in characters:  # présent dans une réplique : il fait partie de la distribution de la scène
            if c not in sc.setdefault("characters", []):
                sc["characters"].append(c)
        tags = {"characters": list(dict.fromkeys(characters)), "location": location or "",
                "outfits": {c: o for c, o in outfits.items() if o}}
        # Même vide, le choix est gardé : sinon le défaut réapparaîtrait après un clic pour tout retirer.
        sc.setdefault("line_tags", {})[str(line)] = tags
        S.save(st)
    return {"ok": True}

def _tags_summary(sc: dict) -> list[str]:
    """Une ligne par réplique bulletée, pour le modèle qui découpe."""
    out = []
    for n in range(len(sc.get("dialogue", []))):
        key, tags = str(n), _effective_tags(sc, n)
        parts = []
        if tags.get("characters"):
            parts.append(t("shots.tag_present", names=", ".join(tags["characters"])))
        if tags.get("location"):
            parts.append(t("shots.tag_place", location=tags["location"]))
        for c, o in (tags.get("outfits") or {}).items():
            parts.append(t("shots.tag_outfit", character=c, outfit=o))
        if parts:
            out.append(t("shots.tag_line", n=int(key) + 1, parts="; ".join(parts)))
    return out

def _ask_shots(st: dict, sc: dict, max_plans: int) -> dict:
    """Demande le découpage au LLM d'écriture. Renvoie le JSON brut."""
    lines = [f"{n}. {l['speaker']} : {l['text']}" for n, l in enumerate(sc.get("dialogue", []), 1)]
    tags = _tags_summary(sc)
    user = t("shots.user", title=sc["title"], summary=sc.get("summary", ""), location=sc.get("location"),
             characters=", ".join(sc.get("characters", [])), lines="\n".join(lines))
    if tags:
        user += "\n\n" + t("shots.tags") + "\n" + "\n".join(tags)
    provider = appsettings.provider("text")
    system = t("shots.system", framings=", ".join(SC.FRAMINGS), max=max_plans)
    return llm.extract_json(llm.complete_task("prompt", system, user, provider))

def normalize_shots(raw, n_lines: int, max_plans: int) -> list[dict]:
    """Nettoie la proposition : bornes, ordre, doublons, limite. Toujours au moins un plan à la première réplique."""
    items = raw.get("plans", []) if isinstance(raw, dict) else (raw or [])
    shots: dict[int, dict] = {}
    for it in items:
        try:
            line = int(it.get("from_line")) - 1
        except (TypeError, ValueError, AttributeError):
            continue
        text = " ".join(str((it or {}).get("text", "")).split())
        if not 0 <= line < n_lines or not text or line in shots:
            continue
        framing = it.get("framing") if it.get("framing") in SC.FRAMINGS else "medium shot"
        shots[line] = {"from_line": line, "framing": framing, "text": text}
    out = [shots[k] for k in sorted(shots)][:max_plans]
    if not out:
        out = [{"from_line": 0, "framing": "medium shot", "text": "Plan d'ensemble de la scène."}]
    out[0]["from_line"] = 0
    return out

def propose_plans(sid: str) -> dict:
    with S.LOCK:
        st = S.load()
        sc = _find_scene(st, sid)
    if not sc.get("dialogue"):
        raise ValueError("Écrivez d'abord les répliques de cette scène")
    return _start("Découpage", _propose_work, sid)

def _propose_work(job_id: str, sid: str) -> None:
    _say(job_id, f"Scène {sid} : découpage en plans…")
    with S.LOCK:
        st = S.load()
    sc = _find_scene(st, sid)
    limit = _proposal_cap(st)
    shots = normalize_shots(_ask_shots(st, sc, limit), len(sc["dialogue"]), limit)
    _replace_plans(sid, [{"from_line": s["from_line"], "text": s["text"], "framing": s["framing"]} for s in shots])

def _new_asset(data: dict, sid: str, title: str, summary: str) -> str:
    base = f"scene_{sid}_{uuid.uuid4().hex[:6]}"
    A.add_asset(data, base, "scene", title, summary)
    return base

def _chars_from_tags(sc: dict, start: int, end: int) -> list[str]:
    """Personnages présents pendant les répliques [start, end) : ceux que l'auteur a cochés. Vide si aucune bulle."""
    chosen: list[str] = []
    for n in range(start, min(end, len(sc.get("dialogue", [])))):
        for c in _effective_tags(sc, n).get("characters", []):
            if c not in chosen:
                chosen.append(c)
    return chosen

def _replace_plans(sid: str, items: list[dict]) -> None:
    """Remplace le découpage d'une scène. Les images déjà faites restent dans le registre, détachées."""
    with S.LOCK:
        st = S.load()
        sc = _find_scene(st, sid)
    with A.LOCK:
        data = A.load()
        plans = []
        bounds = [it["from_line"] for it in items] + [len(sc.get("dialogue", []))]
        for k, it in enumerate(items, 1):
            asset_id = _new_asset(data, sid, f"{sc['title']} · plan {k}", sc.get("summary", ""))
            framing = it.get("framing") or "medium shot"
            chars = _chars_from_tags(sc, bounds[k - 1], bounds[k])
            plans.append({"id": f"p{k}", "from_line": it["from_line"], "asset": asset_id,
                          "characters": chars or shot_characters(it.get("text", ""), sc, framing),
                          "shot": {"framing": framing, "angle": "", "note": it.get("text", "")}})
        A.save(data)
    refresh_outfit_decisions(st, sc, plans)
    with S.LOCK:
        st = S.load()
        target = _find_scene(st, sid)
        target["plans"] = plans
        apply_continuity(target, A.load()["assets"])
        S.save(st)

def save_plans(sid: str, items: list[dict]) -> dict:
    """Enregistre le découpage modifié à la main. Garde les images des plans qui existent encore."""
    with S.LOCK:
        st = S.load()
        sc = _find_scene(st, sid)
    n_lines = len(sc.get("dialogue", []))
    if not items:
        raise ValueError("Une scène a au moins un plan")  # pas de plafond : autant que l'on veut
    cleaned = []
    for it in items:
        line = int(it.get("from_line", 0))
        # Une image seule peut venir après la dernière réplique (from_line == nombre de répliques).
        last_ok = line == n_lines and bool(it.get("pause"))
        if not (0 <= line < n_lines or last_ok):
            raise ValueError("Un plan commence sur une réplique qui n'existe pas")
        chosen = it.get("characters")  # None : le personnage suit le texte du plan
        if chosen is not None:
            chosen = [c for c in sc.get("characters", []) if c in chosen]
            if not chosen:
                raise ValueError("Un plan montre au moins un personnage : désélectionnez-en un seul, pas tous.")
        speaker = str(it.get("speaker", "")).strip()
        if speaker and speaker != "Narration" and speaker not in sc.get("characters", []):
            raise ValueError("La personne qui parle sur cette image doit être un personnage de la scène")
        cleaned.append({"id": it.get("id"), "from_line": line, "text": str(it.get("text", "")).strip(),
                        "characters": chosen, "pause": bool(it.get("pause")),
                        "speaker": speaker, "speech": str(it.get("speech", "")).strip(),
                        "viewpoint": it.get("viewpoint")})  # None : on garde le point de vue existant
    # Un plan « image seule » (sans réplique) peut précéder le plan qui commence sur la même réplique.
    cleaned.sort(key=lambda x: (x["from_line"], 0 if x["pause"] else 1))
    kinds: dict[int, list[bool]] = {}
    for c in cleaned:
        kinds.setdefault(c["from_line"], []).append(c["pause"])
    for line, flags in kinds.items():
        # Plusieurs images seules peuvent se suivre ; au plus un plan normal, en dernier.
        if flags.count(False) > 1 or (False in flags and flags[-1] is not False):
            raise ValueError("Deux plans ne peuvent pas commencer sur la même réplique "
                             "(sauf un plan « image seule » placé juste avant)")
    cleaned[0]["from_line"] = 0
    old = {p["id"]: p for p in sc.get("plans", [])}
    taken: set[str] = set()  # identifiants déjà attribués dans ce découpage
    plans = []
    with A.LOCK:
        data = A.load()
        for k, c in enumerate(cleaned, 1):
            # Un plan garde son image seulement s'il est le premier à porter cet identifiant.
            if c["id"] in old and c["id"] not in taken:
                prev = old[c["id"]]
                asset_id = prev["asset"]
                shot = {**(prev.get("shot") or {}), "note": c["text"]}
                if (prev.get("shot") or {}).get("note", "") != c["text"]:
                    # Texte modifié : l'ancien prompt et l'ancien cadrage ne décrivent plus le plan.
                    # Le prochain « Refaire » rédige un prompt neuf à partir du nouveau texte.
                    shot["framing"] = ""
                    if asset_id in data["assets"]:
                        data["assets"][asset_id]["prompt"] = ""
                else:
                    shot.setdefault("framing", "medium shot")
                pid = prev["id"]
            else:
                # Nouvel identifiant jamais utilisé : deux plans ne peuvent pas partager une image.
                asset_id = _new_asset(data, sid, f"{sc['title']} · plan {k}", sc.get("summary", ""))
                shot = {"framing": "medium shot", "angle": "", "note": c["text"]}
                n = 1
                while f"p{n}" in taken or f"p{n}" in old:
                    n += 1
                pid = f"p{n}"
            taken.add(pid)
            characters = c["characters"] or shot_characters(c["text"], sc, shot["framing"])
            # Les réglages du plan (références, continuité, point de vue…) survivent à l'enregistrement du découpage.
            keep = {k: v for k, v in (old.get(pid) or {}).items()
                    if k not in ("id", "from_line", "characters", "asset", "shot", "pause", "speaker", "speech")}
            plan = {**keep, "id": pid, "from_line": c["from_line"], "characters": characters, "asset": asset_id,
                    "shot": shot}
            if c["viewpoint"] is not None:
                if c["viewpoint"]:
                    plan["viewpoint"] = c["viewpoint"]
                else:
                    plan.pop("viewpoint", None)
            if c["pause"]:
                plan["pause"] = True
                if c["speech"]:  # réplique tapée librement sur une image sans dialogue
                    plan["speaker"] = c["speaker"] or "Narration"
                    plan["speech"] = c["speech"]
            plans.append(plan)
        A.save(data)
    refresh_outfit_decisions(st, sc, plans)
    with S.LOCK:
        st = S.load()
        target = _find_scene(st, sid)
        target["plans"] = plans
        apply_continuity(target, A.load()["assets"])
        S.save(st)
    return {"ok": True, "plans": len(plans)}

def make_plan_image(sid: str, pid: str, prompt: str | None = None) -> dict:
    with S.LOCK:
        sc = _find_scene(S.load(), sid)
        _find_plan(sc, pid)
    if not sc.get("dialogue"):
        raise ValueError("Écrivez d'abord les répliques de cette scène")
    if prompt is not None and not prompt.strip():
        raise ValueError("Le prompt est vide")
    return _start("Image de plan", lambda job_id: _plan_work(job_id, sid, pid, prompt))

def make_all_plans() -> dict:
    with S.LOCK:
        st = S.load()
    with A.LOCK:
        assets = A.load()["assets"]
    todo = [(sc["id"], p["id"]) for sc in S.all_scenes(st) for p in sc.get("plans", [])
            if _url(assets.get(p["asset"], {}), RE.plan_index(p, assets.get(p["asset"], {}))) is None]
    if not todo:
        raise ValueError("Tous les plans ont déjà leur image" if any(sc.get("plans") for sc in S.all_scenes(st))
                         else "Proposez d'abord le découpage des scènes")
    return _start("Images des plans", _all_plans_work, todo)

def _all_plans_work(job_id: str, todo: list) -> None:
    for sid, pid in todo:
        _check_cancel(job_id)
        _plan_work(job_id, sid, pid)

def _plan_work(job_id: str, sid: str, pid: str, prompt: str | None = None) -> None:
    _say(job_id, f"Scène {sid}, plan {pid} : préparation…")
    with S.LOCK:
        st = S.load()
    _ensure_descriptors(st)
    sc = _find_scene(st, sid)
    k, plan = _find_plan(sc, pid)
    refresh_outfit_decisions(st, sc, sc.get("plans", []))  # appels réseau, hors verrou
    decisions = {p["id"]: p["outfit_change"] for p in sc.get("plans", []) if p.get("outfit_change")}
    # Le découpage a pu changer pendant les appels : on repart de l'état enregistré, sans jamais
    # réécrire la liste de plans de l'instantané.
    with S.LOCK:
        st = S.load()
        sc = _find_scene(st, sid)
        k, plan = _find_plan(sc, pid)
        changed = _merge_outfit_decisions(sc, decisions)
        with A.LOCK:
            data = A.load()
        if apply_continuity(sc, data["assets"]) or changed:
            S.save(st)
    info = SC.plan_refs(data["assets"], sc, plan)
    if info["missing"]:
        raise ValueError("Il manque encore une image pour : " + ", ".join(info["missing"]))
    if not prompt:
        prompt = data["assets"][plan["asset"]].get("prompt")
    if not prompt:
        _say(job_id, f"Scène {sid}, plan {pid} : description de l'image…")
        prompt = SC.suggest(st, data, sc, k)
    prompt = prompt.strip()
    with A.LOCK:  # le prompt utilisé est enregistré tout de suite, comme pour les ancres
        data = A.load()
        data["assets"][plan["asset"]]["prompt"] = prompt
        A.save(data)
    _say(job_id, f"Scène {sid}, plan {pid} : dessin (plusieurs minutes possibles)…")
    _check_cancel(job_id)
    idx = A.generate_candidate(plan["asset"], info["refs"], prompt, None, "replicate", None,
                               on_progress=_progress(job_id), on_submit=_submit(job_id))
    _check_cancel(job_id)  # arrêt demandé pendant le dessin : l'image reste candidate, non retenue
    with A.LOCK:
        data = A.load()
        data["assets"][plan["asset"]]["prompt"] = prompt
        A.set_status(data, plan["asset"], idx, True)
        A.save(data)

def set_continuity(sid: str, pid: str, on: bool) -> dict:
    """Active ou désactive la continuité d'un plan (« tenue d'origine » quand elle est désactivée)."""
    with S.LOCK:  # lecture, modification et écriture sans relâcher le verrou
        st = S.load()
        sc = _find_scene(st, sid)
        _, plan = _find_plan(sc, pid)
        plan["continuity"] = bool(on)
        with A.LOCK:
            assets = A.load()["assets"]
        apply_continuity(sc, assets)
        S.save(st)
    return {"ok": True}

def save_refs(sid: str, pid: str, exclude: list, extra: list) -> dict:
    """Réglage fin : coche ou décoche les références automatiques, ajoute ou retire des images."""
    with A.LOCK:
        assets = A.load()["assets"]
    for ref in extra:
        if ref not in assets or assets[ref].get("validated_candidate") is None:
            raise ValueError("Cette image n'est pas encore retenue : elle ne peut pas servir de référence.")
    with S.LOCK:
        st = S.load()
        sc = _find_scene(st, sid)
        _, plan = _find_plan(sc, pid)
        plan["refs_exclude"] = [str(k) for k in exclude]
        plan["refs_extra"] = [r for r in extra if r != plan["asset"]]
        # Chaque référence automatique a désormais une décision explicite, qui prime sur la continuité.
        info = SC.plan_refs(A.load()["assets"], sc, plan)
        plan["manual_refs"] = {a["key"]: (a["key"] in plan["refs_exclude"]) for a in info["auto"] if a.get("key")}
        S.save(st)
    return {"ok": True}

def copy_plan_image(sid: str, pid: str, source: str, candidate: int) -> dict:
    """Met une copie d'une image existante dans un plan (glisser-déposer). Le plan source ne change pas :
    « Refaire » sur l'un ne touche pas l'autre."""
    with S.LOCK:
        st = S.load()
        sc = _find_scene(st, sid)
        _, plan = _find_plan(sc, pid)
    with A.LOCK:
        data = A.load()
    src = data["assets"].get(source)
    if src is None or not 0 <= candidate < len(src.get("candidates", [])):
        raise ValueError("Image introuvable")
    cand = dict(src["candidates"][candidate])
    origin = paths.data_root() / cand["file"]
    if not origin.exists():
        raise ValueError("Fichier de l'image introuvable")
    new_id = f"scene_{sid}_{uuid.uuid4().hex[:6]}"
    folder = paths.data_root() / "assets" / new_id
    folder.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(origin, folder / "cand_00.png")
    cand["file"] = f"assets/{new_id}/cand_00.png"
    with A.LOCK:
        data = A.load()
        A.add_asset(data, new_id, "scene", f"{sc['title']} · plan {pid} (copie)", sc.get("summary", ""))
        data["assets"][new_id].update(status="validated", validated_candidate=0, candidates=[cand],
                                      prompt=src.get("prompt", ""))
        A.save(data)
    with S.LOCK:
        st = S.load()
        target = _find_plan(_find_scene(st, sid), pid)[1]
        target["asset"] = new_id
        target.pop("candidate", None)
        S.save(st)
    return {"ok": True, "asset": new_id}
