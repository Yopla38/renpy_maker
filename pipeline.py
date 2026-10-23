"""Pipeline automatique : plan → répliques → éléments → ancres.

S'arrête avant la sélection des images : les ancres générées doivent ensuite être retenues
par l'auteur (page Ancres). Chaque étape est idempotente : elle ne refait pas ce qui existe.
Une seule exécution à la fois. Le journal est lu par la page Automatique.
"""

from __future__ import annotations

import re
import threading
import traceback
import unicodedata

import assets as A
import plan as P
import prompts as PR
import scenes as SC
import story as S

STATE = {"state": "idle", "stage": "", "log": [], "error": None}
_run_lock = threading.Lock()


def _log(msg: str) -> None:
    STATE["log"].append(msg)
    STATE["log"] = STATE["log"][-300:]


def _slug(text: str) -> str:
    plain = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "_", plain).strip("_")[:40] or "element"


KIND_FR = {"character": "personnage", "outfit": "tenue", "location": "lieu", "object": "objet"}


def create_element(st: dict, data: dict, kind: str, name: str, description: str = "",
                   parent_name: str | None = None) -> tuple[str, bool]:
    """Retourne (identifiant, créé). Réutilise l'élément existant s'il désigne la même chose."""
    assets = data["assets"]
    chars = {S.norm(a["name"]): k for k, a in assets.items() if a["kind"] == "character"}
    el = {"kind": kind, "name": name, "parent_name": parent_name}
    found = SC.match_registry(name, kind, assets) if kind in ("location", "object") \
        else PR.match_asset(assets, el, chars)
    if found:
        return found, False
    parent = None
    if kind == "outfit":
        parent = chars.get(S.norm(parent_name or ""))
        if parent is None:
            raise ValueError(f"personnage « {parent_name} » absent du registre")
    prefix = {"character": "char", "outfit": "outfit", "location": "loc", "object": "obj"}[kind]
    base = f"{prefix}_{_slug(name)}"
    aid, n = base, 2
    while aid in assets:
        aid, n = f"{base}_{n}", n + 1
    A.add_asset(data, aid, kind, name, description, parent)
    if kind == "character":
        try:
            descriptor = PR.describe_person(st, name, description)
            if descriptor:
                data["assets"][aid]["descriptor"] = descriptor
        except Exception as e:  # sans descriptif, le prompt parle de « person » : à reprendre
            _log(f"  genre et âge non déterminés pour « {name} » : {e}")
    try:
        data["assets"][aid]["prompt"] = PR.suggest(st, data, aid)
    except Exception as e:  # le prompt reste vide : l'auteur l'écrit ou réessaie
        _log(f"  prompt non proposé pour « {name} » : {e}")
    return aid, True


def stage_plan(sizes: list[int], guidance: str = "") -> None:
    STATE["stage"] = "plan"
    _log("plan : préparation des chapitres…")
    with S.LOCK:
        done = len(S.load()["chapters"])
    for n in sizes[done:]:
        with S.LOCK:
            st = S.load()
        _log(f"plan : écriture d'un chapitre de {n} scène(s)…")
        ch = P.generate_chapter(st, n, guidance, None)
        with S.LOCK:
            st = S.load()
            P.add_generated(st, ch)
            S.save(st)
        _log(f"plan : {ch['id']} « {ch['title']} » ({n} scènes)")
    if done >= len(sizes):
        _log("plan : déjà présent, rien à faire")


def stage_dialogue() -> None:
    STATE["stage"] = "répliques"
    with S.LOCK:
        todo = [sc["id"] for sc in S.all_scenes(S.load()) if not sc.get("dialogue")]
    for sid in todo:
        _log(f"répliques : écriture de {sid}…")
        with S.LOCK:
            st = S.load()
        lines = P.generate_dialogue(st, sid)
        with S.LOCK:
            st = S.load()
            sc = next(x for x in S.all_scenes(st) if x["id"] == sid)
            sc["dialogue"] = lines
            S.save(st)
        _log(f"répliques : {sid} ({len(lines)} lignes)")
    if not todo:
        _log("répliques : déjà présentes, rien à faire")


def stage_elements() -> list[str]:
    """Crée les éléments manquants. Renvoie les identifiants utilisés par l'histoire (pour les ancres)."""
    STATE["stage"] = "éléments"
    with S.LOCK:
        st = S.load()
    with A.LOCK:
        data = A.load()
    created = 0
    used: list[str] = []

    def use(kind, name, desc="", parent=None):
        nonlocal created
        aid, new = create_element(st, data, kind, name, desc, parent_name=parent)
        created += new
        _log(f"  {KIND_FR[kind]} « {name} » : {'créé' if new else 'déjà au registre'}")
        if aid not in used:
            used.append(aid)
        return aid

    for sc in S.all_scenes(st):
        _log(f"éléments : scène {sc['id']} · {sc['title']}")
        for name in sc.get("characters", []):
            use("character", name)
        if sc.get("location"):
            use("location", sc["location"], sc.get("summary", ""))
        for char, outfit in sc.get("outfits", {}).items():
            use("outfit", outfit, "", parent=char)
        _log(f"éléments : recherche des lieux et objets visibles dans {sc['id']}…")
        found = SC.detect_elements(st, sc, data["assets"])
        _log(f"éléments : {len(found)} élément(s) relevé(s) dans {sc['id']}")
        for v in found:
            if v["kind"] == "decor":
                # Décor (foule, couples, ambiance) : une description dans l'image, pas un personnage ni une ancre.
                if v["name"] not in sc.setdefault("decor", []):
                    sc["decor"].append(v["name"])
                    _log(f"  décor de {sc['id']} : « {v['name']} » (décrit dans le prompt, pas d'ancre)")
            elif v["kind"] == "character":
                use("character", v["name"], v.get("description", ""))
                if v["name"] not in sc.get("characters", []):
                    sc.setdefault("characters", []).append(v["name"])
                    _log(f"éléments : « {v['name']} » ajouté à la scène {sc['id']}")
            else:
                use(v["kind"], v["name"], v.get("description", ""))
    with S.LOCK:
        S.save(st)
    with A.LOCK:
        A.save(data)
    _log(f"éléments : {created} créé(s), {len(used)} utilisé(s)")
    return used


def needed_assets(st: dict, data: dict) -> list[str]:
    """Identifiants du registre utilisés par l'histoire (personnages, lieux, objets, tenues)."""
    assets = data["assets"]
    chars = {S.norm(a["name"]): k for k, a in assets.items() if a["kind"] == "character"}
    out: list[str] = []
    for el in S.story_elements(st):
        aid = PR.match_asset(assets, el, chars) if el["kind"] == "outfit" else (
            SC.match_registry(el["name"], el["kind"], assets) if el["kind"] in ("location",) else
            PR.match_asset(assets, el, chars))
        if aid and aid not in out:
            out.append(aid)
    return out


def stage_anchors(used: list[str]) -> None:
    STATE["stage"] = "ancres"
    _log("ancres : recherche des éléments à illustrer…")
    with S.LOCK:
        st = S.load()
    with A.LOCK:
        data = A.load()
    assets = data["assets"]
    wanted = list(dict.fromkeys(used + needed_assets(st, data)))
    # Personnages, lieux, objets d'abord, puis tenues (qui s'appuient sur l'ancre du personnage).
    order = sorted(wanted, key=lambda k: assets[k]["kind"] == "outfit")
    for aid in order:
        a = assets[aid]
        if a["candidates"]:
            continue
        if a["kind"] == "outfit":
            parent = assets.get(a.get("parent") or "")
            if not parent or parent.get("validated_candidate") is None:
                _log(f"ancres : tenue « {a['name']} » en attente de l'ancre retenue de son personnage")
                continue
            refs = [a["parent"]]
        else:
            refs = []
        _log(f"ancres : génération de « {a['name']} » ({'édition à partir de son personnage' if refs else 'génération pure'})…")
        if not a.get("prompt"):
            with S.LOCK:
                st = S.load()
            with A.LOCK:
                data = A.load()
            data["assets"][aid]["prompt"] = PR.suggest(st, data, aid)
            with A.LOCK:
                A.save(data)
        with A.LOCK:
            data = A.load()
            prompt = data["assets"][aid]["prompt"]
        A.generate_candidate(aid, refs, prompt, None, "replicate")
        _log(f"ancres : « {a['name']} » générée, à retenir dans la page Ancres")
    _log("ancres : terminé")


def run(sizes: list[int], guidance: str = "") -> None:
    if not _run_lock.acquire(blocking=False):
        raise RuntimeError("Une exécution est déjà en cours")
    STATE.update(state="running", error=None, log=[], stage="")
    try:
        _log(f"démarrage : chapitres {sizes}" + (f" · consigne : {guidance}" if guidance else ""))
        stage_plan(sizes, guidance)
        stage_dialogue()
        used = stage_elements()
        stage_anchors(used)
        STATE.update(state="done", stage="ancres")
        _log("pipeline terminé : validez maintenant les ancres")
    except Exception as e:
        traceback.print_exc()
        STATE.update(state="error", error=f"{type(e).__name__}: {e}")
        _log(f"arrêt : {type(e).__name__}: {e}")
    finally:
        _run_lock.release()


def start(sizes: list[int], guidance: str = "") -> None:
    threading.Thread(target=run, args=(sizes, guidance), daemon=True).start()


def anchors_only() -> None:
    """Génère les ancres manquantes (tenues en attente de leur personnage, par exemple)."""
    if not _run_lock.acquire(blocking=False):
        raise RuntimeError("Une exécution est déjà en cours")
    STATE.update(state="running", error=None, log=[], stage="")
    try:
        stage_anchors([])
        STATE.update(state="done", stage="ancres")
    except Exception as e:
        traceback.print_exc()
        STATE.update(state="error", error=f"{type(e).__name__}: {e}")
        _log(f"arrêt : {type(e).__name__}: {e}")
    finally:
        _run_lock.release()


def anchors_view() -> dict:
    """Ancres de l'histoire (personnages, lieux, objets, tenues) avec leurs candidats."""
    with S.LOCK:
        st = S.load()
    with A.LOCK:
        data = A.load()
    assets = data["assets"]
    ids = list(dict.fromkeys(needed_assets(st, data) + [k for k, a in assets.items() if a["kind"] == "object"]))
    rows = []
    for aid in ids:
        a = assets[aid]
        retained = a.get("validated_candidate")
        rows.append({
            "id": aid, "name": a["name"], "kind": a["kind"], "parent": a.get("parent"),
            "prompt": a.get("prompt", ""), "retained": retained,
            "candidates": [{"index": i, "file": c["file"], "retained": i == retained}
                           for i, c in enumerate(a["candidates"])],
            "ready": retained is not None,
        })
    rows.sort(key=lambda r: (r["kind"] == "outfit", r["kind"], r["name"]))
    return {"anchors": rows, "all_ready": bool(rows) and all(r["ready"] for r in rows)}
