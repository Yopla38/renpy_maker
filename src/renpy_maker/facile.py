"""Parcours simple : style → idée → personnages → lieux → tenues → histoire → plans → jeu.

Ce module ne fait qu'enchaîner les fonctions existantes (plan, répliques, registre, scènes, export).
Les créations longues tournent dans un fil : la page suit l'avancement par /api/facile/jobs/<id>.
Une seule création à la fois : les appels réseau sont lents, deux à la fois se gêneraient.

Une scène compte plusieurs plans : chacun démarre à une réplique et montre une image (plan large,
gros plan sur un personnage, détail…). Le découpage est proposé par le LLM, puis modifiable.
"""

from __future__ import annotations

import shutil
import time

from renpy_maker import assets as A
from renpy_maker import appsettings
from renpy_maker import background
from renpy_maker import paths
from renpy_maker import pipeline as PL
from renpy_maker import plan as P
from renpy_maker import projects as PJ
from renpy_maker import atelier as AT
from renpy_maker import story_graph
from renpy_maker import renpy_export as RE
from renpy_maker import story as S
from renpy_maker.facile_base import (
    PLAN_LIMITS,
    SCENE_COUNTS,
    NotFound,
    line_candidates,
    _characters,
    _find_scene,
    _locations,
    _max_plans,
    _outfits,
    _url,
    available_loras,
)
from renpy_maker.facile_elements import (
    _element_card,
    create_outfit,
    edit_outfit,
    redo_card,
    set_asset_loras,
    set_character_mode,
    set_element_refs,
    suggest_identity,
    suggest_prompt,
    update_element,
)
from renpy_maker.facile_jobs import JOBS, _busy, _say, _start, cancel_job
from renpy_maker.facile_plans import (
    _effective_tags,
    _plan_view,
    copy_plan_image,
    make_all_plans,
    make_plan_image,
    propose_plans,
    save_plans,
    save_refs,
    set_continuity,
    set_line_tags,
    update_line,
)
from renpy_maker.facile_settings import save_secret, save_settings, set_max_plans, settings_view

"""Parcours simple : style → idée → personnages → lieux → tenues → histoire → plans → jeu.

Ce module ne fait qu'enchaîner les fonctions existantes (plan, répliques, registre, scènes, export).
Les créations longues tournent dans un fil : la page suit l'avancement par /api/facile/jobs/<id>.
Une seule création à la fois : les appels réseau sont lents, deux à la fois se gêneraient.

Une scène compte plusieurs plans : chacun démarre à une réplique et montre une image (plan large,
gros plan sur un personnage, détail…). Le découpage est proposé par le LLM, puis modifiable.
"""

def play_view() -> dict:
    """L'histoire telle que la joue le lecteur : scènes, répliques, images aux bons moments."""
    with S.LOCK:
        st = S.load()
    with A.LOCK:
        assets = A.load()["assets"]
    scenes = []
    for ch in st["chapters"]:
        for sc in ch["scenes"]:
            # Un plan « image seule » devient une ligne : vide, ou porteuse de la réplique tapée sur l'image.
            n = len(sc.get("dialogue", []))
            solo: dict[int, list[dict]] = {}
            for p in sc.get("plans", []):
                if p.get("pause"):
                    solo.setdefault(p["from_line"], []).append(p)
            lines, index_of, plan_index = [], {}, {}

            def solo_line(p: dict) -> dict:
                if p.get("speech"):
                    return {"speaker": p.get("speaker") or "Narration", "text": p["speech"]}
                return {"speaker": "", "text": "", "pause": True}

            for i, line in enumerate(sc.get("dialogue", [])):
                for p in solo.get(i, []):
                    plan_index[p["id"]] = len(lines)
                    lines.append(solo_line(p))
                index_of[i] = len(lines)
                lines.append(line)
            for p in solo.get(n, []):  # image seule après la dernière réplique
                plan_index[p["id"]] = len(lines)
                lines.append(solo_line(p))
            images = []
            for plan in sorted(sc.get("plans", []), key=lambda p: (p["from_line"], 0 if p.get("pause") else 1)):
                a = assets.get(plan["asset"])
                url = _url(a, RE.plan_index(plan, a)) if a else None
                if not url:
                    continue
                start = plan_index[plan["id"]] if plan.get("pause") else index_of.get(plan["from_line"], 0)
                images.append({"from_line": start, "image": url})
            scenes.append({"id": sc["id"], "title": sc["title"], "chapter": ch["title"],
                           "lines": lines, "images": images})
    return {"title": st.get("title") or "Mon histoire", "scenes": scenes}

def validate_map() -> dict:
    """La carte est validée : l'étape suivante (personnages) s'ouvre. Les impasses signalées restent à corriger."""
    with S.LOCK:
        st = S.load()
        if not st["chapters"]:
            raise ValueError("Il n'y a pas encore d'histoire à relier")
        st["map_validated"] = True
        S.save(st)
    return {"ok": True, "problems": story_graph.build(st)["problems"]}


def save_choices(body: dict) -> dict:
    """Remplace les chemins d'une scène (voir story_graph.set_choices)."""
    with S.LOCK:
        st = S.load()
        created = story_graph.set_choices(st, body.get("scene", ""), body.get("choices") or [])
        S.save(st)
    return {"ok": True, "created": created, "map": story_graph.build(st)}


def save_route(body: dict) -> dict:
    """Commence une route à partir d'une image (voir story_graph.start_route)."""
    with S.LOCK:
        st = S.load()
        new_id = story_graph.start_route(st, body.get("scene", ""), body.get("plan", ""),
                                         body.get("label", ""), body.get("title", ""))
        S.save(st)
    return {"ok": True, "scene": new_id}


def undo_route_api(body: dict) -> dict:
    """Annule une route : sa suite revient dans la scène d'origine (voir story_graph.undo_route)."""
    with S.LOCK:
        st = S.load()
        source = story_graph.undo_route(st, body.get("scene", ""))
        S.save(st)
    return {"ok": True, "scene": source}


def branch_api(body: dict) -> dict:
    """Bifurcation à une image : une route vide, reliée par un choix (voir story_graph.branch_at)."""
    with S.LOCK:
        st = S.load()
        route = story_graph.branch_at(st, body.get("scene", ""), body.get("plan", ""),
                                      body.get("label", ""), body.get("title", ""))
        S.save(st)
    return {"ok": True, "scene": route}


def reshape_api(body: dict) -> dict:
    """Rattacher une route à une scène, retirer une route (vers la réserve) ou la rattacher depuis la réserve."""
    action = body.get("action", "")
    with S.LOCK:
        st = S.load()
        result: dict = {"ok": True}
        if action == "rejoin":
            story_graph.rejoin(st, body.get("scene", ""), body.get("target", ""))
        elif action == "detach":
            story_graph.detach(st, body.get("scene", ""))
        elif action == "attach":
            result["scene"] = story_graph.attach(st, body.get("scene", ""), body.get("block", ""),
                                                 body.get("label", ""))
        else:
            raise ValueError("Action inconnue")
        S.save(st)
    return result


def view() -> dict:
    with S.LOCK:
        st = S.load()
    with A.LOCK:
        assets = A.load()["assets"]
    written = bool(st["chapters"])
    # Un personnage accepté, pas encore placé dans une scène, existe déjà dans le registre : il est listé.
    names = _characters(st)
    names += [a["name"] for a in assets.values() if a["kind"] == "character" and a["name"] not in names]
    characters = [_element_card(assets, "character", n) for n in names]
    locations = [_element_card(assets, "location", n) for n in _locations(st)]
    # Points de vue : des éléments rattachés à leur lieu, comme les tenues le sont à leur personnage.
    for loc in locations:
        loc_aid = loc.get("aid") or ""
        loc["viewpoints"] = [{"aid": k, "name": v["name"], "description": v.get("description", ""),
                              "prompt": v.get("prompt", ""), "image": _url(v, v.get("validated_candidate")),
                              "candidate": v.get("validated_candidate") or 0,
                              "ready": v.get("validated_candidate") is not None}
                             for k, v in assets.items() if v["kind"] == "location" and v.get("parent") == loc_aid]
    # Une tenue de la garde-robe, pas encore portée par une scène, existe déjà dans le registre : elle est listée.
    pairs = list(_outfits(st))
    for a in assets.values():
        if a["kind"] == "outfit" and a.get("parent") in assets:
            pair = (assets[a["parent"]]["name"], a["name"])
            if pair not in pairs:
                pairs.append(pair)
    outfits = [_element_card(assets, "outfit", o, parent=c) for c, o in pairs]
    # La tenue par défaut sert de vignette au personnage (son image de base reste disponible).
    by_aid = {o["aid"]: o for o in outfits}
    for c in characters:
        default = by_aid.get(assets.get(c["aid"], {}).get("default_outfit", ""))
        c["default_outfit"] = default["aid"] if default else ""
        c["default_name"] = default["name"] if default else ""
        c["base_image"] = c["image"]
        if default and default.get("image"):
            c["image"] = default["image"]
    cards = [{"id": sc["id"], "title": sc["title"], "summary": sc.get("summary", ""),
              "chapter": ci + 1, "chapter_title": ch["title"],
              "dialogue": sc.get("dialogue", []), "characters": sc.get("characters", []),
              "candidates": line_candidates(st, sc),
              "location": sc.get("location", ""),
              "line_tags": {str(n): _effective_tags(sc, n) for n in range(len(sc.get("dialogue", [])))},
              "plans": [_plan_view(sc, p, assets) for p in sc.get("plans", [])],
              "route_from": story_graph.route_from(st, sc["id"])}
             for ci, ch in enumerate(st["chapters"]) for sc in ch["scenes"]]
    done = {
        "style": S.style_of(st) is not None,
        "idee": written,
        "personnages": written and all(c["ready"] for c in characters),
        "lieux": written and all(c["ready"] for c in locations),
        "tenues": written and all(c["ready"] for c in outfits),
        "histoire": written and all(c["dialogue"] for c in cards),
        "images": written and all(c["plans"] and all(p["image"] for p in c["plans"]) for c in cards),
        "carte": written and bool(st.get("map_validated")),
    }
    return {
        "style": S.style_of(st), "styles": S.style_choices(),
        "title": st.get("title", ""), "idea": st.get("idea", ""),
        "explicit": bool(st["settings"].get("explicit_content")) and not paths.KIDS, "kids": paths.KIDS,
        "count": st["settings"].get("total_scenes") or SCENE_COUNTS[1], "counts": list(SCENE_COUNTS),
        "max_plans": _max_plans(st), "plan_limits": list(PLAN_LIMITS),
        "written": written, "characters": characters, "locations": locations, "outfits": outfits, "scenes": cards,
        "map": story_graph.build(st) if written else None,
        "reserve": st.get("reserve", []),
        "chapters": [{"title": ch["title"], "scenes": len(ch["scenes"])} for ch in st["chapters"]],
        "lora_names": available_loras(),
        "character_mode": st["settings"].get("character_mode"),
        "ref_choices": [{"ref": aid, "label": a.get("name", aid), "image": _url(a, a["validated_candidate"])}
                        for aid, a in assets.items() if a.get("validated_candidate") is not None],
        "done": done, "busy": _busy.locked(),
    }

def set_style(key: str) -> dict:
    if key not in S.styles():
        raise ValueError("Style inconnu")
    with S.LOCK:
        st = S.load()
        if st["chapters"]:
            raise ValueError("L'histoire est déjà écrite : le style ne peut plus changer. Recommencez pour en choisir un autre.")
        st["settings"]["style"] = key
        S.save(st)
    return {"ok": True}

def write_story(title: str, idea: str, count: int, explicit: bool) -> dict:
    if paths.KIDS:
        explicit = False  # application pour enfants et adolescents : jamais de contenu explicite
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
        if paths.KIDS:
            appsettings.set_provider("text", "replicate")  # seul fournisseur disponible sur l'application
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
    _elements_work(job_id)  # les répliques viennent à l'étape Histoire, quand les personnages sont validés

def complete() -> dict:
    """Reprend une histoire interrompue : éléments manquants (personnages, lieux, tenues)."""
    with S.LOCK:
        st = S.load()
    if not st["chapters"]:
        raise ValueError("Il n'y a pas encore d'histoire à compléter")
    return _start("Compléter l'histoire", _elements_work)

def write_dialogues() -> dict:
    """Écrit les répliques des scènes qui n'en ont pas encore (étape Histoire)."""
    with S.LOCK:
        st = S.load()
    if not st["chapters"]:
        raise ValueError("Il n'y a pas encore d'histoire")
    if all(sc.get("dialogue") for sc in S.all_scenes(st)):
        raise ValueError("Toutes les scènes ont déjà leurs répliques")
    return _start("Répliques", _dialogues_work)

def _dialogues_work(job_id: str) -> None:
    with S.LOCK:
        todo = [sc["id"] for sc in S.all_scenes(S.load()) if not sc.get("dialogue")]
    for sid in todo:
        _write_dialogue(job_id, sid)

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
    _elements_work(job_id)

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

def _elements_work(job_id: str) -> None:
    """Crée les personnages, lieux et tenues de l'histoire qui n'existent pas encore au registre."""
    with S.LOCK:
        st = S.load()
    with A.LOCK:
        data = A.load()
    before = set(data["assets"])
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
    PL.save_created_assets(data, before)

def _write_dialogue(job_id: str, sid: str) -> None:
    _say(job_id, f"Répliques de la scène {sid}…")
    with S.LOCK:
        st = S.load()
    lines = P.generate_dialogue(st, sid)
    with S.LOCK:
        st = S.load()
        target = _find_scene(st, sid)
        target["dialogue"] = lines
        target.pop("line_tags", None)  # les bulles visaient l'ancien texte : on les efface
        S.save(st)

def redo_dialogue(sid: str) -> dict:
    with S.LOCK:
        _find_scene(S.load(), sid)
    return _start("Répliques", lambda job_id: _write_dialogue(job_id, sid))

def set_scene_meta(sid: str, title: str | None = None, summary: str | None = None) -> dict:
    """Titre et résumé d'une scène, corrigés à la main (studio)."""
    with S.LOCK:
        st = S.load()
        sc = next((x for x in S.all_scenes(st) if x["id"] == sid), None)
        if sc is None:
            raise ValueError("Scène inconnue")
        if title is not None:
            title = " ".join(str(title).split())
            if not title:
                raise ValueError("Le titre ne peut pas être vide")
            sc["title"] = title[:120]
        if summary is not None:
            sc["summary"] = str(summary).strip()[:2000]
        S.save(st)
    return {"ok": True}

def export_game() -> dict:
    with S.LOCK:
        st = S.load()
    with A.LOCK:
        data = A.load()
    info = RE.export(st, data)  # lève ValueError si un point bloque
    _, warnings = RE.split_problems(st, data)
    if RE.renpy_sh().is_file():
        lint = RE.lint()
    else:  # sans SDK, le projet est écrit mais ne peut être ni vérifié ni lancé
        lint = {"ok": None, "skipped": f"SDK Ren'Py introuvable ({RE.renpy_sh()}) : vérification non faite",
                "errors": [], "tail": []}
    return {"export": info, "warnings": warnings, "lint": lint}

def launch_game() -> dict:
    if not RE.renpy_sh().is_file():
        raise ValueError(f"SDK Ren'Py introuvable ({RE.renpy_sh()}) : réglez renpy.sdk_dir dans config.yaml")
    return RE.launch()

def reset() -> dict:
    """Met l'histoire et le registre d'images à zéro. Une copie est gardée dans work/backups/."""
    if _busy.locked():
        raise ValueError("Une création est en cours : attendez qu'elle se termine.")
    stamp = time.strftime("%Y%m%d-%H%M%S")
    backup = paths.data_root() / "work" / "backups" / f"facile-{stamp}"
    backup.mkdir(parents=True, exist_ok=True)
    with S.LOCK:
        if paths.story_file().exists():
            shutil.copy(paths.story_file(), backup / "story.yaml")
        S.save(S.new_story())
    with A.LOCK:
        if paths.assets_file().exists():
            shutil.copy(paths.assets_file(), backup / "assets.yaml")
        A.save({"version": 1, "assets": {}})
    return {"ok": True, "backup": str(backup)}

def route(method: str, path: str, body: dict) -> dict:
    if method == "GET":
        if path == "/api/facile":
            return view()
        if path == "/api/facile/settings":
            return settings_view()
        if path == "/api/facile/play":
            return play_view()
        if path == "/api/facile/projects":
            return {"projects": PJ.list_projects(), "current": PJ.current()}
        if path.startswith("/api/facile/jobs/"):
            job = JOBS.get(path.rsplit("/", 1)[-1])
            if job is None:
                raise NotFound("tâche inconnue")
            return job
    elif method == "POST":
        routes = {
            "/api/facile/style": lambda: set_style(body["style"]),
            "/api/facile/map/validate": validate_map,
            "/api/facile/map/choices": lambda: save_choices(body),
            "/api/facile/route/start": lambda: save_route(body),
            "/api/facile/route/undo": lambda: undo_route_api(body),
            "/api/facile/branch": lambda: branch_api(body),
            "/api/atelier/idea": lambda: (AT.set_idea(body.get("title", ""), body.get("idea", "")), {"ok": True})[1],
            "/api/atelier/characters/propose": lambda: {"characters": AT.propose_characters(
                body.get("idea", ""), body.get("existing", []), int(body.get("count", 3)))},
            "/api/atelier/characters/add": lambda: {"aid": AT.add_character(
                body.get("name", ""), body.get("description", ""), body.get("descriptor", ""))},
            "/api/atelier/location/propose": lambda: AT.propose_location(
                body.get("idea", ""), body.get("existing", []), body.get("context", "")),
            "/api/atelier/scene/start": lambda: {"scene": AT.start_scene(
                body.get("title", ""), body.get("location", ""), body.get("characters", []), body.get("summary", ""))},
            "/api/atelier/outfit/default": lambda: (AT.set_default_outfit(body.get("character", ""), body.get("outfit", "")), {"ok": True})[1],
            "/api/facile/outfit/edit": lambda: edit_outfit(body.get("aid", ""), body.get("mode", ""),
                                                           body.get("text", ""), body.get("ref") or None),
            "/api/atelier/shot/propose": lambda: {"text": AT.propose_shot(
                body.get("scene", ""), body.get("plan", ""), body.get("previous", ""))},
            "/api/atelier/viewpoints/propose": lambda: {"viewpoints": AT.propose_viewpoints(
                body.get("location", ""), body.get("description", ""), body.get("idea", ""),
                body.get("existing", []), int(body.get("count", 3)))},
            "/api/atelier/viewpoints/add": lambda: {"aid": AT.add_viewpoint(
                body.get("location", ""), body.get("name", ""), body.get("description", ""))},
            "/api/atelier/outfits/propose": lambda: {"outfits": AT.propose_outfits(
                body.get("character", ""), body.get("description", ""), body.get("idea", ""),
                body.get("existing", []), int(body.get("count", 3)))},
            "/api/atelier/line/propose": lambda: AT.propose_line(body.get("scene", "")),
            "/api/atelier/moment/add": lambda: {"plan": AT.add_moment(
                body.get("scene", ""), body.get("speaker", ""), body.get("text", ""))},
            "/api/facile/reshape": lambda: reshape_api(body),
            "/api/facile/projects/create": lambda: PJ.open_project(PJ.create(body.get("name", ""), body.get("idea", "")), _busy.locked() or background.running() > 0),
            "/api/facile/projects/open": lambda: PJ.open_project(body.get("id", ""), _busy.locked() or background.running() > 0),
            "/api/facile/projects/rename": lambda: PJ.rename(body.get("id", ""), body.get("name", "")),
            "/api/facile/projects/delete": lambda: PJ.delete(body.get("id", "")),
            "/api/facile/settings": lambda: save_settings(body),
            "/api/facile/secret": lambda: save_secret(body.get("name", ""), body.get("value", "")),
            "/api/facile/asset/loras": lambda: set_asset_loras(body["asset"], body.get("loras", [])),
            "/api/facile/job/cancel": lambda: cancel_job(body.get("job", "")),
            "/api/facile/character-mode": lambda: set_character_mode(body.get("mode", "")),
            "/api/facile/identity/suggest": lambda: suggest_identity(body["aid"]),
            "/api/facile/dialogue/line": lambda: update_line(body["scene"], int(body["line"]), body.get("speaker", ""), body.get("text", "")),
            "/api/facile/line-tags": lambda: set_line_tags(body["scene"], int(body["line"]), body.get("characters", []),
                                                           body.get("location", ""), body.get("outfits", {})),
            "/api/facile/element/refs": lambda: set_element_refs(body["aid"], body.get("refs", []), body.get("based_on")),
            "/api/facile/outfit/create": lambda: create_outfit(body["character"], body.get("name", ""),
                                                               body.get("description", ""), body.get("scenes", [])),
            "/api/facile/element/update": lambda: update_element(body["aid"], body.get("name"), body.get("description"),
                                                                 body.get("descriptor"), body.get("prompt")),
            "/api/facile/settings/max-plans": lambda: set_max_plans(int(body["max_plans"])),
            "/api/facile/story": lambda: write_story(body.get("title", ""), body.get("idea", ""),
                                                     int(body.get("count", 4)), bool(body.get("explicit"))),
            "/api/facile/complete": complete,
            "/api/facile/dialogues": write_dialogues,
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
            "/api/facile/scene/meta": lambda: set_scene_meta(body["scene"], body.get("title"), body.get("summary")),
            "/api/facile/export": export_game,
            "/api/facile/launch": launch_game,
            "/api/facile/reset": reset,
        }
        if path in routes:
            return routes[path]()
    raise NotFound("introuvable")
