"""Parcours simple : style → idée → personnages → lieux → tenues → histoire → plans → jeu.

Ce module ne fait qu'enchaîner les fonctions existantes (plan, répliques, registre, scènes, export).
Les créations longues tournent dans un fil : la page suit l'avancement par /api/facile/jobs/<id>.
Une seule création à la fois : les appels réseau sont lents, deux à la fois se gêneraient.

Une scène compte plusieurs plans : chacun démarre à une réplique et montre une image (plan large,
gros plan sur un personnage, détail…). Le découpage est proposé par le LLM, puis modifiable.
"""

from __future__ import annotations

import re
import shutil
import threading
import yaml
import time
import traceback
import unicodedata
import uuid
from pathlib import Path

import assets as A
import image_replicate as REP
import llm
import pipeline as PL
import plan as P
import prompts as PR
import renpy_export as RE
import scenes as SC
import story as S

ROOT = Path(__file__).resolve().parent
SCENE_COUNTS = (3, 4, 5, 6)
PLAN_LIMITS = tuple(range(1, 9))
JOBS: dict[str, dict] = {}
_busy = threading.Lock()


class NotFound(LookupError):
    pass


# ---------- utilitaires ----------

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
    return int(st["settings"].get("max_plans") or 5)


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


def _refs_for(assets: dict, aid: str) -> list[str]:
    """Référence d'une carte : une tenue se dessine à partir de l'image validée de son personnage."""
    a = assets[aid]
    if a["kind"] != "outfit":
        return []
    parent = assets.get(a.get("parent") or "")
    if not parent or parent.get("validated_candidate") is None:
        raise ValueError(f"Dessinez d'abord le personnage « {parent['name'] if parent else '?'} » : "
                         "sa tenue s'appuie sur son image.")
    return [a["parent"]]


def _url(asset: dict, idx: int | None) -> str | None:
    if idx is None or not 0 <= idx < len(asset.get("candidates", [])):
        return None
    return "/files/" + asset["candidates"][idx]["file"]


def _element_card(assets: dict, kind: str, name: str, parent: str | None = None) -> dict:
    aid = _aid(assets, kind, name, parent)
    a = assets.get(aid) if aid else None
    idx = a.get("validated_candidate") if a else None
    blocked = False
    if a and kind == "outfit":
        blocked = assets.get(a.get("parent") or "", {}).get("validated_candidate") is None
    return {"name": name, "aid": aid, "image": _url(a, idx) if a else None, "ready": idx is not None,
            "prompt": a.get("prompt", "") if a else "", "blocked": blocked, "parent": parent or ""}


def apply_continuity(sc: dict, assets: dict) -> bool:
    """Continuité : à partir du deuxième plan, l'image du plan précédent est la référence principale.
    Elle montre l'état réel des personnages (veste retirée, cheveux défaits). Les tenues des personnages
    présents dans les deux plans sont alors mises de côté. Renvoie True si le découpage a changé."""
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
        want_excl = []
        if use:
            shared = set(SC.plan_characters(sc, prev)) & set(SC.plan_characters(sc, plan))
            want_excl = [f"tenue:{S.norm(n)}" for n in sorted(shared) if n in sc.get("outfits", {})]
        old_excl = plan.get("continuity_excluded", [])
        if sorted(old_excl) != sorted(want_excl):
            excl = [k for k in plan.get("refs_exclude", []) if k not in old_excl]
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
    return {"auto": auto, "extra": [e["id"] for e in info["extra"]], "missing": info["missing"]}


def _plan_view(sc: dict, plan: dict, assets: dict) -> dict:
    a = assets.get(plan["asset"], {})
    return {"id": plan["id"], "aid": plan["asset"], "from_line": plan["from_line"],
            "candidate": RE.plan_index(plan, a) if a else None,
            "refs": _refs_view(sc, plan, assets),
            "continuity": bool(plan.get("continuity", True)),
            "characters": SC.plan_characters(sc, plan),
            "text": (plan.get("shot") or {}).get("note", ""),
            "image": _url(a, RE.plan_index(plan, a)) if a else None,
            "prompt": a.get("prompt", "")}


def _ensure_descriptors(st: dict) -> None:
    """Genre et âge de chaque personnage, pour les prompts (complète les anciennes histoires)."""
    with A.LOCK:
        data = A.load()
    missing = [k for k, a in data["assets"].items() if a["kind"] == "character" and not a.get("descriptor")]
    if not missing:
        return
    found = {k: PR.describe_person(st, data["assets"][k]["name"], data["assets"][k].get("description", ""))
             for k in missing}
    with A.LOCK:
        data = A.load()
        for k, word in found.items():
            data["assets"][k]["descriptor"] = word
        A.save(data)


def _ensure_token() -> None:
    REP.ensure_token()


# ---------- réglages (roue) ----------

TEXT_LABELS = {"anthropic": "Anthropic (Claude)", "openai": "OpenAI", "ollama": "Ollama (local)"}


def settings_view() -> dict:
    with S.LOCK:
        st = S.load()
    choices = []
    for name, label in TEXT_LABELS.items():
        cfg = llm.provider_settings(name)
        choices.append({"name": name, "label": label, "model": cfg.get("model", ""),
                        "key": llm.key_available(name)})
    return {
        "text": {"provider": st["settings"]["providers"]["text"], "choices": choices},
        "image": {"provider": st["settings"]["providers"]["image_base"],
                  "choices": [{"name": "replicate", "label": "Replicate (cloud)", "available": True},
                              {"name": "comfyui", "label": "ComfyUI (local), bientôt", "available": False}],
                  "models": ["FLUX dev pour les ancres", "FLUX.2 Klein pour les retouches et les scènes"]},
        "explicit": bool(st["settings"].get("explicit_content")),
    }


def save_settings(body: dict) -> dict:
    provider = body.get("text_provider", "")
    if provider not in TEXT_LABELS:
        raise ValueError("Fournisseur d'écriture inconnu")
    if body.get("image_provider", "replicate") != "replicate":
        raise ValueError("ComfyUI n'est pas encore branché au parcours simple : gardez Replicate.")
    model = str(body.get("text_model", "")).strip()
    if model:
        overrides = {}
        if llm.MODELS_FILE.exists():
            overrides = yaml.safe_load(llm.MODELS_FILE.read_text(encoding="utf-8")) or {}
        overrides.setdefault(provider, {})["model"] = model
        llm.MODELS_FILE.write_text(yaml.safe_dump(overrides, allow_unicode=True), encoding="utf-8")
    with S.LOCK:
        st = S.load()
        st["settings"]["providers"]["text"] = provider
        S.save(st)
    return {"ok": True, **settings_view()}


# ---------- tâches longues ----------

def _start(label: str, work, *args) -> dict:
    if not _busy.acquire(blocking=False):
        raise ValueError("Une création est déjà en cours : elle apparaîtra dès qu'elle sera terminée.")
    job_id = uuid.uuid4().hex[:12]
    JOBS[job_id] = {"state": "running", "label": label, "message": "", "error": None}

    def run():
        try:
            _ensure_token()
            work(job_id, *args)
            JOBS[job_id]["state"] = "done"
        except Exception as e:  # le message est montré à l'utilisateur, la trace reste dans le journal serveur
            traceback.print_exc()
            JOBS[job_id].update(state="error", error=f"{type(e).__name__}: {e}")
        finally:
            _busy.release()

    threading.Thread(target=run, daemon=True).start()
    return {"job": job_id}


def _say(job_id: str, message: str) -> None:
    JOBS[job_id]["message"] = message


# ---------- vue ----------

def view() -> dict:
    with S.LOCK:
        st = S.load()
    with A.LOCK:
        assets = A.load()["assets"]
    written = bool(st["chapters"])
    characters = [_element_card(assets, "character", n) for n in _characters(st)]
    locations = [_element_card(assets, "location", n) for n in _locations(st)]
    outfits = [_element_card(assets, "outfit", o, parent=c) for c, o in _outfits(st)]
    cards = [{"id": sc["id"], "title": sc["title"], "summary": sc.get("summary", ""),
              "chapter": ci + 1, "chapter_title": ch["title"],
              "dialogue": sc.get("dialogue", []), "characters": sc.get("characters", []),
              "plans": [_plan_view(sc, p, assets) for p in sc.get("plans", [])]}
             for ci, ch in enumerate(st["chapters"]) for sc in ch["scenes"]]
    done = {
        "style": S.style_of(st) is not None,
        "idee": written,
        "personnages": written and all(c["ready"] for c in characters),
        "lieux": written and all(c["ready"] for c in locations),
        "tenues": written and all(c["ready"] for c in outfits),
        "histoire": written and all(c["dialogue"] for c in cards),
        "images": written and all(c["plans"] and all(p["image"] for p in c["plans"]) for c in cards),
    }
    return {
        "style": S.style_of(st), "styles": S.style_choices(),
        "title": st.get("title", ""), "idea": st.get("idea", ""),
        "explicit": bool(st["settings"].get("explicit_content")),
        "count": st["settings"].get("total_scenes") or SCENE_COUNTS[1], "counts": list(SCENE_COUNTS),
        "max_plans": _max_plans(st), "plan_limits": list(PLAN_LIMITS),
        "written": written, "characters": characters, "locations": locations, "outfits": outfits, "scenes": cards,
        "chapters": [{"title": ch["title"], "scenes": len(ch["scenes"])} for ch in st["chapters"]],
        "ref_choices": [{"ref": aid, "label": a.get("name", aid), "image": _url(a, a["validated_candidate"])}
                        for aid, a in assets.items() if a.get("validated_candidate") is not None],
        "done": done, "busy": _busy.locked(),
    }


# ---------- style et histoire ----------

def set_style(key: str) -> dict:
    if key not in S.STYLES:
        raise ValueError("Style inconnu")
    with S.LOCK:
        st = S.load()
        if st["chapters"]:
            raise ValueError("L'histoire est déjà écrite : le style ne peut plus changer. Recommencez pour en choisir un autre.")
        st["settings"]["style"] = key
        S.save(st)
    return {"ok": True}


def set_max_plans(n: int) -> dict:
    if n not in PLAN_LIMITS:
        raise ValueError(f"Choisissez entre {PLAN_LIMITS[0]} et {PLAN_LIMITS[-1]} plans")
    with S.LOCK:
        st = S.load()
        st["settings"]["max_plans"] = n
        S.save(st)
    return {"ok": True, "max_plans": n}


def write_story(title: str, idea: str, count: int, explicit: bool) -> dict:
    if not idea.strip():
        raise ValueError("Racontez l'histoire en quelques phrases")
    if count not in SCENE_COUNTS:
        raise ValueError("Choisissez entre 3 et 6 scènes")
    with S.LOCK:
        st = S.load()
        if S.style_of(st) is None:
            raise ValueError("Choisissez d'abord le style")
        if st["chapters"]:
            raise ValueError("Une histoire existe déjà : recommencez pour en écrire une autre.")
        st["title"] = title.strip()
        st["idea"] = idea.strip()
        st["synopsis"] = idea.strip()
        st["settings"]["explicit_content"] = bool(explicit)
        st["settings"]["total_scenes"] = count
        S.save(st)
    return _start("Écriture de l'histoire", _write_work, count)


def _write_work(job_id: str, count: int) -> None:
    _say(job_id, "Écriture du plan des scènes…")
    with S.LOCK:
        st = S.load()
    ch = P.generate_chapter(st, count, "", None)
    with S.LOCK:
        st = S.load()
        P.add_generated(st, ch)
        if not st["title"]:
            st["title"] = ch["title"]
        S.save(st)
    _complete_work(job_id)


def complete() -> dict:
    """Reprend une histoire interrompue : répliques et éléments manquants uniquement."""
    with S.LOCK:
        st = S.load()
    if not st["chapters"]:
        raise ValueError("Il n'y a pas encore d'histoire à compléter")
    return _start("Compléter l'histoire", _complete_work)


def add_chapter(count: int, guidance: str = "") -> dict:
    """Ajoute un chapitre à la suite de l'histoire : plan, répliques, nouveaux éléments."""
    if count not in SCENE_COUNTS:
        raise ValueError("Choisissez entre 3 et 6 scènes")
    with S.LOCK:
        st = S.load()
    if not st["chapters"]:
        raise ValueError("Écrivez d'abord l'histoire")
    return _start("Nouveau chapitre", _chapter_work, count, guidance.strip())


def _chapter_work(job_id: str, count: int, guidance: str) -> None:
    _say(job_id, "Écriture du nouveau chapitre…")
    with S.LOCK:
        st = S.load()
    ch = P.generate_chapter(st, count, guidance, None)
    with S.LOCK:
        st = S.load()
        P.add_generated(st, ch)
        st["settings"]["total_scenes"] = len(S.all_scenes(st))
        S.save(st)
    _complete_work(job_id)


def delete_last_chapter() -> dict:
    """Retire le dernier chapitre (avec ses scènes). Les images restent dans le registre, sans être utilisées."""
    if _busy.locked():
        raise ValueError("Une création est en cours : attendez qu'elle se termine.")
    with S.LOCK:
        st = S.load()
        if len(st["chapters"]) < 2:
            raise ValueError("L'histoire garde au moins un chapitre.")
        removed = st["chapters"].pop()
        st["settings"]["total_scenes"] = len(S.all_scenes(st))
        S.save(st)
    return {"ok": True, "removed": removed["title"]}


def _complete_work(job_id: str) -> None:
    with S.LOCK:
        todo = [sc["id"] for sc in S.all_scenes(S.load()) if not sc.get("dialogue")]
    for sid in todo:
        _write_dialogue(job_id, sid)
    with S.LOCK:
        st = S.load()
    with A.LOCK:
        data = A.load()
    _say(job_id, "Personnages et lieux…")
    scenes = S.all_scenes(st)
    for name in _characters(st):
        PL.create_element(st, data, "character", name)
    for name in _locations(st):
        summary = next(sc.get("summary", "") for sc in scenes if sc.get("location") == name)
        PL.create_element(st, data, "location", name, summary)
    chars = set(_characters(st))
    for char, outfit in _outfits(st):
        if char in chars:
            PL.create_element(st, data, "outfit", outfit, "", parent_name=char)
    with A.LOCK:
        A.save(data)


def _write_dialogue(job_id: str, sid: str) -> None:
    _say(job_id, f"Répliques de la scène {sid}…")
    with S.LOCK:
        st = S.load()
    lines = P.generate_dialogue(st, sid)
    with S.LOCK:
        st = S.load()
        _find_scene(st, sid)["dialogue"] = lines
        S.save(st)


def redo_dialogue(sid: str) -> dict:
    with S.LOCK:
        _find_scene(S.load(), sid)
    return _start("Répliques", lambda job_id: _write_dialogue(job_id, sid))


# ---------- personnages, lieux, tenues : une image par carte ----------

def redo_card(aid: str, prompt: str | None = None) -> dict:
    with A.LOCK:
        assets = A.load()["assets"]
    if aid not in assets:
        raise ValueError("Élément inconnu")
    _refs_for(assets, aid)  # refuse tout de suite une tenue sans image de son personnage
    if prompt is not None and not prompt.strip():
        raise ValueError("Le prompt est vide")
    return _start("Image", _card_work, aid, prompt)


def _card_work(job_id: str, aid: str, prompt: str | None = None) -> None:
    with S.LOCK:
        _ensure_descriptors(S.load())
    with A.LOCK:
        data = A.load()
    a = data["assets"][aid]
    refs = _refs_for(data["assets"], aid)
    if not prompt:
        prompt = a.get("prompt")
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
    idx = A.generate_candidate(aid, refs, prompt, None, "replicate", None)
    with A.LOCK:
        data = A.load()
        A.set_status(data, aid, idx, True)
        A.save(data)


# ---------- découpage en plans ----------

SHOT_SYSTEM = """You split a scene of a visual novel into camera shots, one still image per shot.
Answer ONLY with JSON: {"plans": [{"from_line": <number of the dialogue line where the shot starts, starting at 1>,
"framing": "<one of: """ + ", ".join(SC.FRAMINGS) + """>", "text": "<one short French sentence: what the shot shows>"}]}
Rules:
- The first shot starts at line 1 and shows the whole place with everyone in it (wide or medium shot).
- Then, when the speaker changes or an emotion matters, add a close-up on the character who speaks
  (text: 'Gros plan sur Léa, qui ...').
- Add a detail shot when an object or a place from the story deserves it (text: 'Détail : la carte aux bords jaunis').
- If a character takes off or puts on a clothing item, or changes their look, say it in the text
  (for example 'Léa sans sa veste', 'Tom ébouriffé, la chemise ouverte').
- Use at most {max} shots. Keep them in order of dialogue lines. Never more than one shot per line."""


def _ask_shots(st: dict, sc: dict, max_plans: int) -> dict:
    """Demande le découpage au LLM d'écriture. Renvoie le JSON brut."""
    lines = [f"{n}. {l['speaker']} : {l['text']}" for n, l in enumerate(sc.get("dialogue", []), 1)]
    user = (f"Scene : {sc['title']} — {sc.get('summary', '')}\n"
            f"Location : {sc.get('location') or 'unknown'}\n"
            f"Characters : {', '.join(sc.get('characters', []))}\n"
            "Dialogue :\n" + "\n".join(lines))
    provider = st["settings"]["providers"]["text"]
    return llm.extract_json(llm.complete(provider, SHOT_SYSTEM.replace("{max}", str(max_plans)), user))


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
    limit = _max_plans(st)
    shots = normalize_shots(_ask_shots(st, sc, limit), len(sc["dialogue"]), limit)
    _replace_plans(sid, [{"from_line": s["from_line"], "text": s["text"], "framing": s["framing"]} for s in shots])


def _new_asset(data: dict, sid: str, title: str, summary: str) -> str:
    base = f"scene_{sid}_{uuid.uuid4().hex[:6]}"
    A.add_asset(data, base, "scene", title, summary)
    return base


def _replace_plans(sid: str, items: list[dict]) -> None:
    """Remplace le découpage d'une scène. Les images déjà faites restent dans le registre, détachées."""
    with S.LOCK:
        st = S.load()
        sc = _find_scene(st, sid)
    with A.LOCK:
        data = A.load()
        plans = []
        for k, it in enumerate(items, 1):
            asset_id = _new_asset(data, sid, f"{sc['title']} · plan {k}", sc.get("summary", ""))
            framing = it.get("framing") or "medium shot"
            plans.append({"id": f"p{k}", "from_line": it["from_line"], "asset": asset_id,
                          "characters": shot_characters(it.get("text", ""), sc, framing),
                          "shot": {"framing": framing, "angle": "", "note": it.get("text", "")}})
        A.save(data)
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
    limit = _max_plans(st)
    n_lines = len(sc.get("dialogue", []))
    if not 1 <= len(items) <= limit:
        raise ValueError(f"Une scène a entre 1 et {limit} plan(s)")
    cleaned = []
    for it in items:
        line = int(it.get("from_line", 0))
        if not 0 <= line < n_lines:
            raise ValueError("Un plan commence sur une réplique qui n'existe pas")
        chosen = it.get("characters")  # None : le personnage suit le texte du plan
        if chosen is not None:
            chosen = [c for c in sc.get("characters", []) if c in chosen]
            if not chosen:
                raise ValueError("Un plan montre au moins un personnage : désélectionnez-en un seul, pas tous.")
        cleaned.append({"id": it.get("id"), "from_line": line, "text": str(it.get("text", "")).strip(),
                        "characters": chosen})
    cleaned.sort(key=lambda x: x["from_line"])
    lines = [c["from_line"] for c in cleaned]
    if len(set(lines)) != len(lines):
        raise ValueError("Deux plans ne peuvent pas commencer sur la même réplique")
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
            plans.append({"id": pid, "from_line": c["from_line"], "characters": characters, "asset": asset_id, "shot": shot})
        A.save(data)
    with S.LOCK:
        st = S.load()
        target = _find_scene(st, sid)
        target["plans"] = plans
        apply_continuity(target, A.load()["assets"])
        S.save(st)
    return {"ok": True, "plans": len(plans)}


# ---------- images des plans ----------

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
    return _start("Images des plans", lambda job_id: [_plan_work(job_id, sid, pid) for sid, pid in todo])


def _plan_work(job_id: str, sid: str, pid: str, prompt: str | None = None) -> None:
    _say(job_id, f"Scène {sid}, plan {pid} : préparation…")
    with S.LOCK:
        st = S.load()
    _ensure_descriptors(st)
    sc = _find_scene(st, sid)
    k, plan = _find_plan(sc, pid)
    with A.LOCK:
        data = A.load()
    if apply_continuity(sc, data["assets"]):
        with S.LOCK:
            cur = S.load()
            _find_scene(cur, sid)["plans"] = sc["plans"]
            S.save(cur)
    info = SC.plan_refs(data["assets"], sc, plan)
    if info["missing"]:
        raise ValueError("Il manque encore une image pour : " + ", ".join(info["missing"]))
    if info["too_many"]:
        raise ValueError("Trop de personnages pour une seule image (5 références au maximum)")
    if not prompt:
        prompt = data["assets"][plan["asset"]].get("prompt")
    if not prompt:
        _say(job_id, f"Scène {sid}, plan {pid} : description de l'image…")
        prompt = SC.suggest(st, data, sc, k)
    prompt = prompt.strip()
    _say(job_id, f"Scène {sid}, plan {pid} : dessin (plusieurs minutes possibles)…")
    idx = A.generate_candidate(plan["asset"], info["refs"], prompt, None, "replicate", None)
    with A.LOCK:
        data = A.load()
        data["assets"][plan["asset"]]["prompt"] = prompt
        A.set_status(data, plan["asset"], idx, True)
        A.save(data)


def set_continuity(sid: str, pid: str, on: bool) -> dict:
    """Active ou désactive la continuité d'un plan (« tenue d'origine » quand elle est désactivée)."""
    with S.LOCK:
        st = S.load()
        sc = _find_scene(st, sid)
        _, plan = _find_plan(sc, pid)
        plan["continuity"] = bool(on)
    with A.LOCK:
        assets = A.load()["assets"]
    apply_continuity(sc, assets)
    with S.LOCK:
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
    origin = ROOT / cand["file"]
    if not origin.exists():
        raise ValueError("Fichier de l'image introuvable")
    new_id = f"scene_{sid}_{uuid.uuid4().hex[:6]}"
    folder = ROOT / "assets" / new_id
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


# ---------- jeu ----------

def export_game() -> dict:
    with S.LOCK:
        st = S.load()
    with A.LOCK:
        data = A.load()
    info = RE.export(st, data)  # lève ValueError si un point bloque
    _, warnings = RE.split_problems(st, data)
    lint = RE.lint()
    return {"export": info, "warnings": warnings, "lint": lint}


def launch_game() -> dict:
    return RE.launch()


# ---------- recommencer ----------

def reset() -> dict:
    """Met l'histoire et le registre d'images à zéro. Une copie est gardée dans work/backups/."""
    if _busy.locked():
        raise ValueError("Une création est en cours : attendez qu'elle se termine.")
    stamp = time.strftime("%Y%m%d-%H%M%S")
    backup = ROOT / "work" / "backups" / f"facile-{stamp}"
    backup.mkdir(parents=True, exist_ok=True)
    with S.LOCK:
        if S.STORY.exists():
            shutil.copy(S.STORY, backup / "story.yaml")
        S.save(S.new_story())
    with A.LOCK:
        if A.SPEC.exists():
            shutil.copy(A.SPEC, backup / "assets.yaml")
        A.save({"version": 1, "assets": {}})
    return {"ok": True, "backup": str(backup)}


# ---------- routage HTTP ----------

def route(method: str, path: str, body: dict) -> dict:
    if method == "GET":
        if path == "/api/facile":
            return view()
        if path == "/api/facile/settings":
            return settings_view()
        if path.startswith("/api/facile/jobs/"):
            job = JOBS.get(path.rsplit("/", 1)[-1])
            if job is None:
                raise NotFound("tâche inconnue")
            return job
    elif method == "POST":
        routes = {
            "/api/facile/style": lambda: set_style(body["style"]),
            "/api/facile/settings": lambda: save_settings(body),
            "/api/facile/settings/max-plans": lambda: set_max_plans(int(body["max_plans"])),
            "/api/facile/story": lambda: write_story(body.get("title", ""), body.get("idea", ""),
                                                     int(body.get("count", 4)), bool(body.get("explicit"))),
            "/api/facile/complete": complete,
            "/api/facile/chapter/add": lambda: add_chapter(int(body.get("count", 4)), body.get("guidance", "")),
            "/api/facile/chapter/delete-last": delete_last_chapter,
            "/api/facile/card": lambda: redo_card(body["aid"], body.get("prompt")),
            "/api/facile/prompt/suggest": lambda: suggest_prompt(body["kind"], body["id"]),
            "/api/facile/dialogue": lambda: redo_dialogue(body["scene"]),
            "/api/facile/scene/propose": lambda: propose_plans(body["scene"]),
            "/api/facile/scene/plans": lambda: save_plans(body["scene"], body.get("plans", [])),
            "/api/facile/plan/image": lambda: make_plan_image(body["scene"], body["plan"], body.get("prompt")),
            "/api/facile/plan/images": make_all_plans,
            "/api/facile/plan/continuity": lambda: set_continuity(body["scene"], body["plan"], bool(body["on"])),
            "/api/facile/plan/refs": lambda: save_refs(body["scene"], body["plan"], body.get("exclude", []),
                                                       body.get("extra", [])),
            "/api/facile/plan/copy-image": lambda: copy_plan_image(body["scene"], body["plan"], body["source"],
                                                                   int(body["candidate"])),
            "/api/facile/export": export_game,
            "/api/facile/launch": launch_game,
            "/api/facile/reset": reset,
        }
        if path in routes:
            return routes[path]()
    raise NotFound("introuvable")
