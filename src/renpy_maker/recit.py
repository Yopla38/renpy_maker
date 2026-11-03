"""Mode récit : un jeu de rôle guidé, où l'histoire s'écrit devant le joueur.

Le joueur donne le cadre (idée, ambiance, style) et prépare ses personnages. Ensuite, à chaque pas, le conteur
(le modèle de langage) propose le moment suivant : une voix off, une réplique, et l'image (garder celle qui est à
l'écran, ou une nouvelle avec son cadrage). Le joueur garde, modifie, ou dit en langage naturel ce qui doit changer :
un « metteur en scène » (le modèle, encore) applique la consigne au moment proposé ou à une image déjà faite.

Les données restent celles des autres modes, pour que l'histoire se lise partout :
- une ligne de vie est une suite de scènes reliées par `next` ; une scène change avec le lieu ;
- un choix est un `choice` de scène : chaque option ouvre une scène (une ligne à vivre) ;
- une ligne qui attend sa suite est marquée `open` ; une ligne en rejoint une autre par `next` ;
- une voix off est une réplique du locuteur « Narration » ; une image est un plan, et garder l'image
  précédente revient à ne pas créer de plan.
Les propositions n'écrivent rien : seules les actions du joueur modifient l'histoire.
"""

from __future__ import annotations

import json
import uuid

from renpy_maker import appsettings, llm, paths
from renpy_maker import assets as A
from renpy_maker import atelier as AT
from renpy_maker import facile as FA
from renpy_maker import facile_plans as FP
from renpy_maker import prompts as PR
from renpy_maker import renpy_export as RE
from renpy_maker import scenes as SC
from renpy_maker import story as S
from renpy_maker import story_graph as SG
from renpy_maker.facile_base import NotFound, _find_plan, _find_scene, _key
from renpy_maker.facile_elements import _card_work, create_outfit
from renpy_maker.facile_jobs import _busy, _check_cancel, _say, _start
from renpy_maker.facile_plans import _plan_work

MAX_CHOICES = 3     # choix proposés par le conteur (le joueur peut en ajouter un, jusqu'à SG.MAX_CHOICES)
HISTORY = 16        # répliques vécues données au conteur comme contexte
DIRECTIONS = 4      # indications durables du joueur gardées pour la suite
AMBIANCES = ("Mystérieuse", "Tendre", "Haletante", "Drôle", "Mélancolique", "Épique")


# ----- petits outils -------------------------------------------------------------------------------------

def _one_line(value) -> str:
    return " ".join(str(value or "").split())


def _same(a, b) -> bool:
    """Même nom, sans tenir compte de la casse ni des accents (la voix et le modèle les perdent souvent)."""
    return _key(str(a or "")) == _key(str(b or ""))


def _recit(st: dict) -> dict:
    return st.setdefault("recit", {})


def _label(text) -> str:
    label = _one_line(text)
    if not label:
        raise ValueError("Le choix a besoin d'un libellé")
    if len(label) > SG.MAX_LABEL:
        raise ValueError(f"Libellé trop long (au plus {SG.MAX_LABEL} caractères)")
    return label


def _short(text: str) -> str:
    """Un choix proposé trop long est raccourci au dernier mot entier."""
    if len(text) <= SG.MAX_LABEL:
        return text
    return text[:SG.MAX_LABEL].rsplit(" ", 1)[0].rstrip(",;:")


def _clean_choices(raw, minimum: int = 2) -> list[str]:
    """Choix proposés par le conteur : courts, sans doublon, deux ou trois. Moins de deux : pas de choix."""
    out: list[str] = []
    for item in raw if isinstance(raw, list) else []:
        text = _short(_one_line(item.get("label") if isinstance(item, dict) else item))
        if text and S.norm(text) not in {S.norm(x) for x in out}:
            out.append(text)
    out = out[:MAX_CHOICES]
    return out if len(out) >= minimum else []


def _ordered_plans(sc: dict) -> list[dict]:
    return sorted(sc.get("plans", []), key=lambda p: (p["from_line"], 0 if p.get("pause") else 1))


def _free_pid(sc: dict) -> str:
    used = {p["id"] for p in sc.get("plans", [])}
    n = 1
    while f"p{n}" in used:
        n += 1
    return f"p{n}"


def _new_asset_id(sid: str) -> str:
    return f"scene_{sid}_{uuid.uuid4().hex[:6]}"


def _cast(assets: dict) -> list[dict]:
    """La distribution : chaque personnage du registre, avec les noms de ses tenues."""
    out = []
    for aid, a in assets.items():
        if a["kind"] != "character":
            continue
        outfits = [o["name"] for o in assets.values() if o["kind"] == "outfit" and o.get("parent") == aid]
        out.append({"aid": aid, "name": a["name"], "description": a.get("description", ""),
                    "descriptor": a.get("descriptor", ""), "outfits": outfits})
    return out


def _location_aid(assets: dict, name: str | None) -> str | None:
    return next((k for k, a in assets.items() if a["kind"] == "location" and not a.get("parent")
                 and _same(a["name"], name)), None)


def _viewpoints(assets: dict, location: str | None) -> list[dict]:
    loc = _location_aid(assets, location)
    if not loc:
        return []
    return [{"aid": k, "name": a["name"]} for k, a in assets.items()
            if a["kind"] == "location" and a.get("parent") == loc]


def _viewpoint_aid(assets: dict, location: str | None, name: str) -> str:
    return next((v["aid"] for v in _viewpoints(assets, location) if _same(v["name"], name)), "")


# ----- lignes de vie ---------------------------------------------------------------------------------------

def is_open(st: dict, sc: dict) -> bool:
    """Ligne qui attend sa suite : ni choix, ni suite, ni fin. Une scène créée ailleurs (atelier) l'est
    si c'est la dernière de l'histoire."""
    if sc.get("choices") or sc.get("next") or sc.get("ending"):
        return False
    if sc.get("open"):
        return True
    scenes = S.all_scenes(st)
    return bool(scenes) and scenes[-1]["id"] == sc["id"]


def _successor(st: dict, sc: dict) -> str | None:
    """Suite directe d'une scène : explicite, sinon la suivante dans l'ordre. None : choix, fin ou ligne ouverte."""
    if sc.get("choices") or sc.get("ending") or sc.get("open"):
        return None
    if sc.get("next"):
        return sc["next"]
    ids = [s["id"] for s in S.all_scenes(st)]
    i = ids.index(sc["id"])
    return ids[i + 1] if i + 1 < len(ids) else None


def _follow(st: dict, sid: str) -> str:
    """Avance tant que la ligne continue toute seule : on s'arrête à une ligne ouverte, un choix ou une fin."""
    by_id = {sc["id"]: sc for sc in S.all_scenes(st)}
    seen = {sid}
    cur = sid
    while True:
        nxt = _successor(st, by_id[cur])
        if nxt is None or nxt not in by_id or nxt in seen:
            return cur
        seen.add(nxt)
        cur = nxt


def path_to(st: dict, sid: str | None) -> list[dict]:
    """Chemin vécu du début jusqu'à une scène : [{"scene", "label"}], label = choix qui mène à cette scène.
    Là où deux lignes se rejoignent, on remonte par celle d'où vient le joueur, sinon par la route d'origine."""
    by_id = {sc["id"]: sc for sc in S.all_scenes(st)}
    if sid not in by_id:
        return []
    preds: dict[str, list[tuple[str, str]]] = {}
    for e in SG.build(st)["edges"]:
        preds.setdefault(e["target"], []).append((e["source"], e["label"] if e["kind"] == "choice" else ""))
    via = (st.get("recit") or {}).get("via") or {}
    path = [{"scene": sid, "label": ""}]
    seen = {sid}
    cur = sid
    while True:
        options = [p for p in preds.get(cur, []) if p[0] not in seen and p[0] in by_id]
        if not options:
            return path
        wanted = [w for w in (via.get(cur), by_id[cur].get("route_of")) if w]
        src, label = next((p for w in wanted for p in options if p[0] == w), options[0])
        path[0]["label"] = label
        path.insert(0, {"scene": src, "label": ""})
        seen.add(src)
        cur = src


def _covering(st: dict, sid: str) -> tuple[dict, dict] | None:
    """La dernière image vécue à la fin de cette scène : la sienne, sinon celle d'une scène d'avant."""
    by_id = {sc["id"]: sc for sc in S.all_scenes(st)}
    for step in reversed(path_to(st, sid)):
        plans = _ordered_plans(by_id[step["scene"]])
        if plans:
            return by_id[step["scene"]], plans[-1]
    return None


def _story_so_far(st: dict, sid: str) -> tuple[list[str], int]:
    """Répliques vécues (les dernières), et nombre de répliques depuis le dernier choix."""
    by_id = {sc["id"]: sc for sc in S.all_scenes(st)}
    lines: list[str] = []
    since, place = 0, None
    for step in path_to(st, sid):
        sc = by_id[step["scene"]]
        if step["label"]:
            lines.append(f"(Le joueur a choisi : « {step['label']} »)")
            since = 0
        if sc.get("location") and sc["location"] != place:
            place = sc["location"]
            lines.append(f"(Lieu : {place})")
        for line in sc.get("dialogue", []):
            lines.append(f"{line['speaker']} : {line['text']}")
            since += 1
    return lines[-HISTORY:], since


def _directions(st: dict, sid: str | None) -> list[str]:
    """Indications durables du joueur : celles de toute l'histoire, puis celles des scènes vécues."""
    by_id = {sc["id"]: sc for sc in S.all_scenes(st)}
    out = list((st.get("recit") or {}).get("directions") or [])
    for step in path_to(st, sid) if sid else []:
        out += by_id[step["scene"]].get("directions") or []
    return out[-DIRECTIONS:]


def _remember(st: dict, sid: str | None, text: str) -> None:
    text = _one_line(text)
    if not text:
        return
    holder = _find_scene(st, sid) if sid else _recit(st)
    holder["directions"] = (holder.get("directions") or [])[-5:] + [text]


def _insert_scene(st: dict, ch: dict, after: dict | None, title: str, location: str | None,
                  characters: list[str], outfits: dict | None) -> dict:
    """Nouvelle scène vide, rangée juste après `after` (en fin de chapitre sans `after`)."""
    new = S.add_scene(ch, SG._next_scene_id(st), title, "", list(characters), location, dict(outfits or {}))
    ch["scenes"].pop()
    ch["scenes"].insert(ch["scenes"].index(after) + 1 if after is not None else len(ch["scenes"]), new)
    ch["scene_count"] = len(ch["scenes"])
    st["settings"]["total_scenes"] = len(S.all_scenes(st))
    st["map_validated"] = False
    return new


def _reuse_plan(sc: dict, src: dict, from_line: int, assets: dict) -> str:
    """Le moment garde l'image d'avant : un plan qui montre la même image, sans nouveau dessin."""
    pid = _free_pid(sc)
    plan = {"id": pid, "from_line": from_line, "asset": src["asset"], "characters": list(src.get("characters") or []),
            "shot": dict(src.get("shot") or {}), "kept": True}
    if src.get("viewpoint"):
        plan["viewpoint"] = src["viewpoint"]
    idx = RE.plan_index(src, assets.get(src["asset"]) or {})
    if idx is not None:
        plan["candidate"] = idx  # l'image vue à ce moment-là, même si l'autre est redessinée ensuite
    sc.setdefault("plans", []).append(plan)
    sc["plans"].sort(key=lambda p: (p["from_line"], 0 if p.get("pause") else 1))
    return pid


def _split(st: dict, sc: dict, cut: int, assets: dict) -> dict:
    """Coupe une scène avant la réplique `cut` : la suite passe dans une nouvelle scène reliée par `next`, qui
    hérite des choix, de la fin ou de l'ouverture. L'image en cours au point de coupe continue dans la suite."""
    ch, _ = SG.find_scene(st, sc["id"])
    old_next = _successor(st, sc)
    was_open = is_open(st, sc)
    plans = _ordered_plans(sc)
    covering = next((p for p in reversed(plans) if p["from_line"] < cut), None)
    tail = _insert_scene(st, ch, sc, f"{sc['title']} (suite)", sc.get("location"), sc.get("characters", []),
                         sc.get("outfits"))
    SG._move_content(sc, cut, {p["id"] for p in plans if p["from_line"] >= cut}, tail)
    if covering and not any(p["from_line"] == 0 for p in tail["plans"]):
        _reuse_plan(tail, covering, 0, assets)
    tail["choices"] = sc.get("choices") or []
    tail["ending"] = bool(sc.get("ending"))
    tail["open"] = was_open
    tail["next"] = old_next if not (tail["choices"] or tail["ending"] or was_open) else None
    if sc.get("return_to"):
        tail["return_to"] = sc.pop("return_to")
    targets = {c["target"] for c in tail["choices"]}
    for other in S.all_scenes(st):  # les routes qui partaient de la fin de la scène partent de la suite
        if other.get("route_of") == sc["id"] and other["id"] in targets:
            other["route_of"] = tail["id"]
    sc.update(choices=[], ending=False, open=False, next=tail["id"])
    rc = _recit(st)
    if was_open and rc.get("current") == sc["id"]:
        rc["current"] = tail["id"]
    rc.pop("last", None)
    return tail


def _default_current(st: dict) -> str | None:
    scenes = S.all_scenes(st)
    opened = [sc["id"] for sc in scenes if is_open(st, sc)]
    return opened[-1] if opened else (scenes[-1]["id"] if scenes else None)


# ----- cadre ---------------------------------------------------------------------------------------------

def set_frame(title: str, idea: str, ambiance: str, style: str | None) -> dict:
    """Le cadre : titre, idée, ambiance et style des images. Le style ne change plus une fois l'histoire commencée."""
    idea = _one_line(idea)
    if not idea:
        raise ValueError("Racontez en quelques mots de quoi parle l'histoire")
    with S.LOCK:
        st = S.load()
        if style:
            if style not in S.STYLES:
                raise ValueError("Style inconnu")
            if st["chapters"] and st["settings"].get("style") != style:
                raise ValueError("L'histoire a déjà commencé : le style des images ne change plus")
            st["settings"]["style"] = style
        elif S.style_of(st) is None:
            raise ValueError("Choisissez le style des images")
        st["title"] = _one_line(title) or st.get("title") or "Mon histoire"
        st["idea"] = idea
        _recit(st)["ambiance"] = _one_line(ambiance)
        S.save(st)
    return {"ok": True}


def set_options(body: dict) -> dict:
    with S.LOCK:
        st = S.load()
        if "auto_draw" in body:
            _recit(st)["auto_draw"] = bool(body["auto_draw"])
        if body.get("drop_pending"):  # « Pas maintenant » : les choix proposés sont écartés
            _recit(st).pop("pending", None)
        S.save(st)
    return {"ok": True}


# ----- le conteur : proposer le moment suivant -----------------------------------------------------------

MOMENT_FORMAT = ('{"voix_off": "...", "speaker": "...", "text": "...", "present": ["..."], "location": null, '
                 '"image": {"keep": false, "shot": "...", "framing": "...", "viewpoint": "", "visible": ["..."]}, '
                 '"choices": []}')


def _safety(st: dict) -> str:
    if st["settings"].get("explicit_content") and not paths.KIDS:
        return ""
    return " Contenu tout public : pas de nudité, pas de scène sexuelle, pas de violence crue."


def _rules(st: dict) -> str:
    return (
        "Tu es le conteur d'un jeu de rôle en roman visuel, en français. Le joueur vit l'histoire pas à pas : tu "
        "écris un seul moment à la fois, court, qui fait avancer l'histoire dans l'ambiance donnée. "
        f"Réponds uniquement par du JSON : {MOMENT_FORMAT}\n"
        "- voix_off : la narration, au présent, une ou deux phrases ; vide si le moment n'en a pas besoin.\n"
        "- speaker et text : au plus une réplique, d'un personnage présent (nom exact), une ou deux phrases "
        "naturelles, sans didascalie ; laisse-les vides si le moment n'est que narration.\n"
        "- present : les personnages présents après ce moment (un personnage de la distribution peut arriver ou "
        "partir).\n"
        "- location : null si l'on reste au même endroit ; sinon {\"name\": \"...\", \"description\": \"...\"} : un "
        "lieu connu (nom exact) ou un nouveau lieu, description du décor seul. Au tout premier moment, donne "
        "toujours un lieu.\n"
        "- image.keep : true si l'image à l'écran convient encore (même cadrage, rien de visible ne change) : on "
        "économise un dessin. false si le cadrage, le point de vue, les personnes visibles, leur posture ou "
        "l'action changent, et toujours au premier moment d'un lieu.\n"
        "- image.shot : si keep vaut false, ce que l'on voit à l'écran en une phrase : cadrage, qui est visible, "
        "posture (assis, debout…), action, décor, lumière.\n"
        f"- image.framing : un de {', '.join(SC.FRAMINGS)}. image.viewpoint : un point de vue du lieu (nom exact) "
        "ou vide. image.visible : les personnages visibles dans l'image.\n"
        "- choices : quand le héros arrive à une décision qui compte (environ toutes les 6 à 10 répliques), "
        f"2 ou {MAX_CHOICES} choix courts (moins de 60 caractères), formulés comme des actions ; sinon [].\n"
        "- Suis les indications du joueur." + _safety(st))


def _context(st: dict, assets: dict, sid: str | None) -> str:
    """Ce que le conteur doit savoir : le cadre, la distribution, le lieu, l'image à l'écran, ce qui s'est passé."""
    rc = st.get("recit") or {}
    style = S.style_of(st)
    parts = [f"Titre : {st.get('title') or '(sans titre)'}",
             f"Histoire : {st.get('idea') or st.get('synopsis') or ''}",
             f"Ambiance : {rc.get('ambiance') or '(libre)'}",
             f"Style des images : {style['name'] if style else '(libre)'}",
             "Distribution :"]
    for c in _cast(assets):
        who = f" ({c['descriptor']})" if c["descriptor"] else ""
        wardrobe = f" Tenues : {', '.join(c['outfits'])}." if c["outfits"] else ""
        parts.append(f"- {c['name']}{who} : {c['description'] or '(non décrit)'}{wardrobe}")
    places = sorted({a["name"] for a in assets.values() if a["kind"] == "location" and not a.get("parent")})
    parts.append(f"Lieux déjà connus : {', '.join(places) or 'aucun'}")
    if sid:
        sc = _find_scene(st, sid)
        loc = assets.get(_location_aid(assets, sc.get("location")) or "") or {}
        parts.append(f"Lieu actuel : {sc.get('location') or '(non précisé)'} — {loc.get('description') or ''}")
        parts.append("Points de vue de ce lieu : "
                     + (", ".join(v["name"] for v in _viewpoints(assets, sc.get("location"))) or "aucun"))
        parts.append(f"Personnages présents : {', '.join(sc.get('characters', [])) or 'personne'}")
        if sc.get("outfits"):
            parts.append("Tenues portées : " + ", ".join(f"{c} : {o}" for c, o in sc["outfits"].items()))
        cov = _covering(st, sid)
        shown = ((cov[1].get("shot") or {}).get("note") or "(sans description)") if cov else "(aucune)"
        parts.append(f"Image à l'écran : {shown}")
        lines, since = _story_so_far(st, sid)
        parts.append("Ce qui s'est passé (le plus récent en dernier) :\n" + ("\n".join(lines) or "(rien encore)"))
        parts.append(f"Répliques depuis le dernier choix : {since}")
    else:
        parts.append("C'est le tout premier moment de l'histoire.")
    directions = _directions(st, sid)
    if directions:
        parts.append("Indications du joueur pour la suite (à respecter) :\n" + "\n".join(f"- {d}" for d in directions))
    return "\n".join(parts)


def _brief(m: dict | None) -> dict:
    m = m or {}
    return {"voix_off": m.get("voix_off", ""), "speaker": m.get("speaker", ""), "text": m.get("text", "")}


def normalize_moment(raw, st: dict, assets: dict, sid: str | None) -> dict:
    """Nettoie une proposition : noms de la distribution, lieu obligatoire au départ, image cohérente."""
    if not isinstance(raw, dict):
        raise ValueError("Proposition illisible : demandez-en une autre")
    cast = [c["name"] for c in _cast(assets)]
    sc = _find_scene(st, sid) if sid else None

    def name_of(value) -> str | None:
        return next((c for c in cast if _same(c, value)), None)

    present = [n for n in (name_of(x) for x in raw.get("present") or []) if n] \
        if isinstance(raw.get("present"), list) else []
    present = list(dict.fromkeys(present)) or list(sc.get("characters", []) if sc else [])
    voix_off, text = _one_line(raw.get("voix_off")), _one_line(raw.get("text"))
    speaker = name_of(raw.get("speaker")) or S.NARRATOR
    if not text:
        speaker = ""
    elif speaker != S.NARRATOR and speaker not in present:
        present.append(speaker)
    if not voix_off and not text:
        raise ValueError("Le conteur n'a rien proposé : demandez une autre proposition")

    location = None
    loc = raw.get("location")
    if isinstance(loc, dict) and _one_line(loc.get("name")):
        name = _one_line(loc["name"])
        known = assets.get(_location_aid(assets, name) or "")
        if sc is None or not _same(name, sc.get("location")):
            location = {"name": known["name"] if known else name,
                        "description": _one_line(loc.get("description")) or (known or {}).get("description", "")}
    if sc is None and location is None:
        raise ValueError("Le conteur n'a pas proposé de lieu pour commencer : demandez une autre proposition")

    img = raw.get("image") if isinstance(raw.get("image"), dict) else {}
    place = location["name"] if location else sc.get("location")
    viewpoint = next((v["name"] for v in _viewpoints(assets, place)
                      if _same(v["name"], img.get("viewpoint"))), "")
    visible = [n for n in (name_of(x) for x in img.get("visible") or []) if n in present] \
        if isinstance(img.get("visible"), list) else []
    if not visible:
        visible = [speaker] if speaker in present else list(present)
    can_keep = sc is not None and location is None and _covering(st, sid) is not None
    framing = img.get("framing") if img.get("framing") in SC.FRAMINGS else ("wide shot" if location else "medium shot")
    return {"scene": sid, "voix_off": voix_off, "speaker": speaker, "text": text, "present": present,
            "location": location,
            "image": {"keep": bool(img.get("keep")) and can_keep, "can_keep": can_keep,
                      "shot": _one_line(img.get("shot")), "framing": framing, "viewpoint": viewpoint,
                      "visible": list(dict.fromkeys(visible))},
            "outfits": {}, "choices": _clean_choices(raw.get("choices"))}


def _snapshot(sid: str | None) -> tuple[dict, dict]:
    with S.LOCK:
        st = S.load()
    with A.LOCK:
        assets = A.load()["assets"]
    if sid:
        _find_scene(st, sid)
    return st, assets


def propose_next(sid: str | None, instruction: str = "", previous: dict | None = None) -> dict:
    """Le moment suivant de la ligne (ou le tout premier moment, sans scène). Rien n'est enregistré."""
    st, assets = _snapshot(sid)
    if not sid and S.all_scenes(st):
        raise ValueError("L'histoire a déjà commencé : choisissez la ligne à continuer")
    if sid and not is_open(st, _find_scene(st, sid)):
        raise ValueError("Cette ligne a déjà une suite : reprenez une ligne ouverte")
    user = _context(st, assets, sid)
    if _one_line(instruction):
        user += f"\nLe joueur demande pour ce moment : {_one_line(instruction)}"
    if previous:
        user += "\nProposition précédente, à ne pas répéter : " + json.dumps(_brief(previous), ensure_ascii=False)
    raw = llm.extract_json(llm.complete_task("dialogue", _rules(st), user, appsettings.provider("text")))
    return normalize_moment(raw, st, assets, sid)


def propose_choices(sid: str) -> dict:
    """Deux ou trois choix pour la suite de la ligne. Rien n'est enregistré."""
    st, assets = _snapshot(sid)
    system = ("Tu proposes les choix d'un jeu de rôle en roman visuel, en français : ce que le héros peut décider "
              "maintenant, en suivant l'histoire. Réponds uniquement par du JSON : {\"choices\": [\"...\"]}. "
              f"2 ou {MAX_CHOICES} choix courts (moins de 60 caractères), formulés comme des actions, vraiment "
              "différents les uns des autres." + _safety(st))
    raw = llm.extract_json(llm.complete_task("dialogue", system, _context(st, assets, sid),
                                             appsettings.provider("text")))
    choices = _clean_choices(raw.get("choices") if isinstance(raw, dict) else None)
    if not choices:
        raise ValueError("Le conteur n'a pas proposé de choix : réessayez")
    return {"choices": choices}


# ----- le joueur garde le moment ---------------------------------------------------------------------------

def commit_moment(sid: str | None, m: dict) -> dict:
    """Le joueur garde le moment : voix off et réplique s'ajoutent à la ligne, avec une nouvelle image ou
    l'image d'avant. Un nouveau lieu ouvre une nouvelle scène, à la suite de la ligne."""
    with A.LOCK:
        assets = A.load()["assets"]
    cast = {c["name"]: c for c in _cast(assets)}
    voix_off, text = _one_line(m.get("voix_off")), _one_line(m.get("text"))
    speaker = str(m.get("speaker") or "").strip() or S.NARRATOR
    if text and speaker != S.NARRATOR and speaker not in cast:
        raise ValueError(f"{speaker} ne fait pas partie de la distribution")
    lines = ([{"speaker": S.NARRATOR, "text": voix_off, "expression": "neutre"}] if voix_off else []) \
        + ([{"speaker": speaker, "text": text, "expression": "neutre"}] if text else [])
    if not lines:
        raise ValueError("Le moment est vide : écrivez une voix off ou une réplique")
    present = [n for n in m.get("present") or [] if n in cast]
    loc = m.get("location") if isinstance(m.get("location"), dict) else None
    loc_name = _one_line(loc.get("name")) if loc else ""
    img = m.get("image") if isinstance(m.get("image"), dict) else {}
    outfits = {}
    for char, outfit in (m.get("outfits") or {}).items():
        real = next((o for o in cast[char]["outfits"] if _same(o, outfit)), None) if char in cast else None
        if real:
            outfits[char] = real
    shot = _one_line(img.get("shot"))
    framing = img.get("framing") if img.get("framing") in SC.FRAMINGS else "medium shot"

    new_asset = None
    with S.LOCK:
        st = S.load()
        rc = _recit(st)
        previous, created = None, False
        if sid is None:
            if S.all_scenes(st):
                raise ValueError("L'histoire a déjà commencé : choisissez la ligne à continuer")
            if not loc_name:
                raise ValueError("Le premier moment a besoin d'un lieu")
            if not st["chapters"]:
                S.add_chapter(st, "ch1", "Chapitre 1", "", 1)
            sc = _insert_scene(st, st["chapters"][-1], None, loc_name, loc_name, present, {})
            created = True
        else:
            sc = _find_scene(st, sid)
            if not is_open(st, sc):
                raise ValueError("Cette ligne a déjà une suite : reprenez une ligne ouverte")
            if loc_name and not _same(loc_name, sc.get("location")):
                ch, _ = SG.find_scene(st, sid)
                new = _insert_scene(st, ch, sc, loc_name, loc_name, present or sc.get("characters", []),
                                    sc.get("outfits"))
                sc.update(next=new["id"], open=False)
                previous, sc, created = sc["id"], new, True
        sc["open"] = True
        for name in present + ([speaker] if text and speaker != S.NARRATOR else []):
            if name not in sc.setdefault("characters", []):
                sc["characters"].append(name)
        for char, outfit in outfits.items():
            sc.setdefault("outfits", {})[char] = outfit
        start = len(sc.get("dialogue", []))
        sc.setdefault("dialogue", []).extend(lines)
        keep = bool(img.get("keep")) and not created
        plan_id = None
        if keep and not sc.get("plans"):  # première image d'une ligne : celle de la scène d'avant continue
            cov = _covering(st, sc["id"])
            if cov:
                plan_id = _reuse_plan(sc, cov[1], start, assets)
            else:
                keep = False
        if not keep:
            plan_id = _free_pid(sc)
            new_asset = _new_asset_id(sc["id"])
            plan = {"id": plan_id, "from_line": start, "asset": new_asset,
                    "characters": [n for n in img.get("visible") or [] if n in sc["characters"]],
                    "shot": {"framing": framing, "angle": "", "note": shot}}
            view = _viewpoint_aid(assets, sc.get("location"), str(img.get("viewpoint") or ""))
            if view:
                plan["viewpoint"] = view
            sc.setdefault("plans", []).append(plan)
        rc["current"] = sc["id"]
        rc["last"] = {"scene": sc["id"], "start": start, "count": len(lines), "plan": plan_id,
                      "created": created, "previous": previous}
        # Les choix proposés avec ce moment attendent le joueur (ils survivent à un rechargement de la page).
        options = _clean_choices(m.get("choices"))
        if options:
            rc["pending"] = {"scene": sc["id"], "options": options}
        else:
            rc.pop("pending", None)
        S.save(st)
        title, location = sc["title"], sc.get("location")
    if new_asset:
        with A.LOCK:
            data = A.load()
            A.add_asset(data, new_asset, "scene", f"{title} · moment {start + 1}", shot)
            A.save(data)
    if created and location:
        AT._ensure_location(location, _one_line((loc or {}).get("description")))
    return {"ok": True, "scene": sc["id"], "plan": plan_id, "draw": bool(new_asset)}


def undo_last() -> dict:
    """Retire le dernier moment gardé (répliques, image, et la scène qu'il avait ouverte)."""
    with S.LOCK:
        st = S.load()
        rc = _recit(st)
        last = rc.get("last")
        if not last:
            raise ValueError("Rien à annuler")
        try:
            ch, sc = SG.find_scene(st, last["scene"])
        except ValueError:
            rc.pop("last", None)
            S.save(st)
            raise ValueError("Ce moment n'existe plus") from None
        if len(sc.get("dialogue", [])) != last["start"] + last["count"]:
            raise ValueError("Le dernier moment a déjà changé : corrigez-le à la main")
        del sc["dialogue"][last["start"]:]
        if last.get("plan"):
            sc["plans"] = [p for p in sc.get("plans", []) if p["id"] != last["plan"]]
        rc["current"] = sc["id"]
        if last.get("created") and not sc["dialogue"]:
            ch["scenes"].remove(sc)
            ch["scene_count"] = len(ch["scenes"])
            if not ch["scenes"]:
                st["chapters"].remove(ch)
            if last.get("previous"):
                _, prev = SG.find_scene(st, last["previous"])
                prev.update(next=None, open=True)
                rc["current"] = prev["id"]
            else:
                rc.pop("current", None)
            st["settings"]["total_scenes"] = len(S.all_scenes(st))
        rc.pop("last", None)
        rc.pop("pending", None)
        S.save(st)
    return {"ok": True}


# ----- choix, bifurcations, rencontres ---------------------------------------------------------------------

def choose(sid: str, options: list, picked: int) -> dict:
    """Le joueur arrive à un choix : chaque option ouvre une ligne à vivre ; il vit celle qu'il a prise.
    Les autres restent ouvertes, on peut les vivre plus tard."""
    labels: list[str] = []
    for option in options or []:
        label = _label(option)
        if S.norm(label) not in {S.norm(x) for x in labels}:
            labels.append(label)
    if not labels:
        raise ValueError("Choisissez au moins une option")
    if len(labels) > SG.MAX_CHOICES:
        raise ValueError(f"Au plus {SG.MAX_CHOICES} choix")
    if not 0 <= int(picked) < len(labels):
        raise ValueError("Option inconnue")
    with S.LOCK:
        st = S.load()
        ch, sc = SG.find_scene(st, sid)
        if not is_open(st, sc):
            raise ValueError("Cette ligne a déjà une suite")
        if not sc.get("dialogue"):
            raise ValueError("Vivez au moins un moment avant de choisir")
        created, after = [], sc
        for label in labels:
            new = _insert_scene(st, ch, after, label, sc.get("location"), sc.get("characters", []), sc.get("outfits"))
            new.update(open=True, route_of=sid)
            created.append(new["id"])
            after = new
        sc.update(choices=[{"target": t, "label": lab} for t, lab in zip(created, labels)],
                  open=False, next=None, ending=False)
        rc = _recit(st)
        rc["current"] = created[int(picked)]
        rc.pop("last", None)
        rc.pop("pending", None)
        S.save(st)
    return {"ok": True, "scene": created[int(picked)], "created": created}


def branch_after(sid: str, line: int, label: str) -> dict:
    """Vivre autrement à partir d'un moment passé : la ligne se sépare après cette réplique. Ce qui suivait
    reste une option (« Continuer »), la nouvelle ligne est à vivre et peut revenir au fil plus tard."""
    label = _label(label)
    with A.LOCK:
        assets = A.load()["assets"]
    with S.LOCK:
        st = S.load()
        ch, sc = SG.find_scene(st, sid)
        n = len(sc.get("dialogue", []))
        if not 0 <= int(line) < n:
            raise ValueError("Réplique inconnue")
        cut = int(line) + 1
        return_to = None
        if cut < n:
            tail = _split(st, sc, cut, assets)
            sc.update(choices=[{"target": tail["id"], "label": "Continuer"}], next=None)
            return_to = tail["id"]
        elif sc.get("choices"):
            if len(sc["choices"]) >= SG.MAX_CHOICES:
                raise ValueError(f"Ce choix a déjà {SG.MAX_CHOICES} options")
        elif sc.get("ending"):
            raise ValueError("Cette ligne se termine ici : rouvrez-la pour la continuer autrement")
        elif is_open(st, sc):
            raise ValueError("Vous êtes au bout de cette ligne : dites simplement ce qui doit se passer")
        else:
            return_to = _successor(st, sc)
            sc.update(choices=[{"target": return_to, "label": "Continuer"}], next=None)
        new = _insert_scene(st, ch, sc, label, sc.get("location"), sc.get("characters", []), sc.get("outfits"))
        new.update(open=True, route_of=sid)
        if return_to:
            new["return_to"] = return_to
        sc["choices"].append({"target": new["id"], "label": label})
        sc.update(open=False, ending=False)
        rc = _recit(st)
        rc["current"] = new["id"]
        rc.pop("last", None)
        S.save(st)
    return {"ok": True, "scene": new["id"], "return_to": return_to}


def rejoin(sid: str, target: str, line: int = 0) -> dict:
    """Rassemble deux lignes : la ligne ouverte `sid` continue dans `target`, au moment qui commence à la
    réplique `line` (la scène est coupée là si besoin)."""
    with A.LOCK:
        assets = A.load()["assets"]
    with S.LOCK:
        st = S.load()
        _, sc = SG.find_scene(st, sid)
        _, tg = SG.find_scene(st, target)
        if tg["id"] == sc["id"]:
            raise ValueError("Une ligne ne peut pas se rejoindre elle-même")
        if not is_open(st, sc):
            raise ValueError("Seule une ligne qui attend sa suite peut en rejoindre une autre")
        if not sc.get("dialogue"):
            raise ValueError("Vivez au moins un moment sur cette ligne avant de la faire rejoindre une autre")
        line = int(line or 0)
        if not 0 <= line <= max(len(tg.get("dialogue", [])) - 1, 0):
            raise ValueError("Moment inconnu dans cette scène")
        if line > 0:
            tg = _split(st, tg, line, assets)
        sc.update(next=tg["id"], open=False)
        sc.pop("return_to", None)
        rc = _recit(st)
        rc.setdefault("via", {})[tg["id"]] = sc["id"]
        rc["current"] = _follow(st, tg["id"])
        rc.pop("last", None)
        S.save(st)
    return {"ok": True, "scene": rc["current"], "joined": tg["id"]}


def finish(sid: str) -> dict:
    """Cette ligne se termine ici : c'est une fin de l'histoire."""
    with S.LOCK:
        st = S.load()
        _, sc = SG.find_scene(st, sid)
        if not is_open(st, sc):
            raise ValueError("Seule une ligne qui attend sa suite peut se terminer ici")
        if not sc.get("dialogue"):
            raise ValueError("Vivez au moins un moment sur cette ligne avant de la terminer")
        sc.update(ending=True, open=False)
        _recit(st).pop("last", None)
        S.save(st)
    return {"ok": True}


def reopen(sid: str) -> dict:
    """Rouvre une ligne terminée, ou une ligne qui en rejoignait une autre : elle attend de nouveau sa suite."""
    with S.LOCK:
        st = S.load()
        _, sc = SG.find_scene(st, sid)
        if sc.get("choices"):
            raise ValueError("Cette scène mène à un choix : vivez l'une de ses options")
        if not (sc.get("ending") or sc.get("next") or is_open(st, sc)):
            raise ValueError("Cette scène continue déjà dans la suivante")
        sc.update(ending=False, next=None, open=True)
        rc = _recit(st)
        rc["current"] = sid
        rc.pop("last", None)
        S.save(st)
    return {"ok": True}


def set_current(sid: str, follow: bool = False) -> dict:
    """La ligne que vit le joueur. Avec `follow`, on avance jusqu'au prochain choix, fin ou ligne ouverte."""
    with S.LOCK:
        st = S.load()
        SG.find_scene(st, sid)
        rc = _recit(st)
        rc["current"] = _follow(st, sid) if follow else sid
        rc.pop("last", None)
        S.save(st)
    return {"ok": True, "scene": rc["current"]}


def set_label(sid: str, target: str, label: str) -> dict:
    label = _label(label)
    with S.LOCK:
        st = S.load()
        _, sc = SG.find_scene(st, sid)
        choice = next((c for c in sc.get("choices") or [] if c["target"] == target), None)
        if choice is None:
            raise ValueError("Choix inconnu")
        choice["label"] = label
        S.save(st)
    return {"ok": True}


def set_outfit(sid: str, character: str, outfit: str) -> dict:
    """Tenue d'un personnage dans cette scène (vide : sa tenue par défaut)."""
    with A.LOCK:
        cast = {c["name"]: c for c in _cast(A.load()["assets"])}
    if character not in cast:
        raise ValueError("Personnage inconnu")
    wanted = _one_line(outfit)
    outfit = next((o for o in cast[character]["outfits"] if _same(o, wanted)), "") if wanted else ""
    if wanted and not outfit:
        raise ValueError(f"{character} n'a pas de tenue « {wanted} »")
    with S.LOCK:
        st = S.load()
        sc = _find_scene(st, sid)
        if outfit:
            sc.setdefault("outfits", {})[character] = outfit
        else:
            (sc.get("outfits") or {}).pop(character, None)
        S.save(st)
    return {"ok": True}


def set_shot(sid: str, pid: str, note: str | None = None, framing: str | None = None,
             viewpoint: str | None = None, characters: list | None = None) -> dict:
    """Réglage à la main d'une image, depuis la roue : ce que l'on voit, le cadrage, le point de vue, les
    personnages visibles. Seul ce moment change : une image gardée d'un moment précédent reste intacte (ce moment
    recevra la sienne au dessin). Un texte modifié efface le prompt de ce moment, qui sera rédigé de nouveau."""
    with A.LOCK:
        assets = A.load()["assets"]
    with S.LOCK:
        st = S.load()
        sc = _find_scene(st, sid)
        _, plan = _find_plan(sc, pid)
        shot = dict(plan.get("shot") or {"framing": "", "angle": "", "note": ""})
        changed = False
        if note is not None and _one_line(note) != shot.get("note", ""):
            shot["note"] = _one_line(note)
            changed = True
        if framing is not None:
            if framing not in SC.FRAMINGS:
                raise ValueError("Cadrage inconnu")
            changed = changed or framing != shot.get("framing")
            shot["framing"] = framing
        plan["shot"] = shot
        if viewpoint is not None:
            if viewpoint and viewpoint not in {v["aid"] for v in _viewpoints(assets, sc.get("location"))}:
                raise ValueError("Ce point de vue n'appartient pas au lieu de la scène")
            changed = changed or viewpoint != (plan.get("viewpoint") or "")
            if viewpoint:
                plan["viewpoint"] = viewpoint
            else:
                plan.pop("viewpoint", None)
        if characters is not None:
            chosen = [c for c in sc.get("characters", []) if c in characters]
            if not chosen:
                raise ValueError("Une image montre au moins un personnage : désélectionnez-en un seul, pas tous.")
            changed = changed or chosen != SC.plan_characters(sc, plan)
            plan["characters"] = chosen
        FP.apply_continuity(sc, assets)
        shared = _shares_image(st, plan)
        S.save(st)
    if changed and not shared:
        with A.LOCK:
            data = A.load()
            if plan["asset"] in data["assets"]:
                data["assets"][plan["asset"]]["prompt"] = ""
                A.save(data)
    return {"ok": True, "changed": changed}


# ----- dessin --------------------------------------------------------------------------------------------

def missing_refs(assets: dict, sc: dict, plan: dict) -> list[str]:
    """Images à dessiner avant ce moment (lieu, personnages, tenues), dans l'ordre où elles se dessinent :
    une tenue après son personnage, un point de vue après son lieu."""
    todo: list[str] = []

    def need(aid: str) -> None:
        a = assets.get(aid)
        if not a or a.get("status") == "validated" or aid in todo:
            return
        if a.get("parent") in assets:
            need(a["parent"])
        todo.append(aid)

    for item in SC.plan_refs(assets, sc, plan)["auto"]:
        if item["id"] and not item["excluded"] and not item["ok"]:
            need(item["id"])
    return todo


def _shares_image(st: dict, plan: dict) -> bool:
    """Ce moment montre l'image d'un autre (image gardée, ou même image dans deux plans)."""
    return bool(plan.get("kept") or "candidate" in plan or any(
        p is not plan and p["asset"] == plan["asset"] for s in S.all_scenes(st) for p in s.get("plans", [])))


def _own_image(sid: str, pid: str) -> None:
    """Un moment qui montrait l'image d'un autre (image gardée) reçoit la sienne avant d'être redessiné :
    l'autre moment ne change pas."""
    with S.LOCK:
        st = S.load()
        sc = _find_scene(st, sid)
        _, plan = _find_plan(sc, pid)
        if not _shares_image(st, plan):
            return
        new_asset = _new_asset_id(sid)
        plan["asset"] = new_asset
        plan.pop("candidate", None)
        plan.pop("kept", None)
        note, title = (plan.get("shot") or {}).get("note", ""), sc["title"]
        S.save(st)
    with A.LOCK:
        data = A.load()
        A.add_asset(data, new_asset, "scene", f"{title} · {pid}", note)
        A.save(data)


def draw(sid: str, pid: str, prompt: str | None = None) -> dict:
    """Dessine l'image d'un moment. Ce qui manque encore (lieu, personnages, tenues) se dessine d'abord."""
    if _busy.locked():
        raise ValueError("Un dessin est déjà en cours : celui-ci attendra qu'il se termine")
    with S.LOCK:
        sc = _find_scene(S.load(), sid)
        _find_plan(sc, pid)
    _own_image(sid, pid)
    prompt = str(prompt).strip() if prompt else None
    return _start("Image du moment", _draw_work, sid, pid, prompt or None)


def _draw_work(job_id: str, sid: str, pid: str, prompt: str | None) -> None:
    with S.LOCK:
        st = S.load()
    sc = _find_scene(st, sid)
    _, plan = _find_plan(sc, pid)
    with A.LOCK:
        assets = A.load()["assets"]
    for aid in missing_refs(assets, sc, plan):
        _check_cancel(job_id)
        _say(job_id, f"D'abord « {assets[aid]['name']} » : dessin…")
        _card_work(job_id, aid)
    _plan_work(job_id, sid, pid, prompt)


# ----- le metteur en scène : consignes en langage naturel ---------------------------------------------------

DIRECT_MOMENT = (
    "Tu es l'assistant de mise en scène d'un jeu de rôle en roman visuel. Voici le moment proposé (JSON) et "
    "l'indication du joueur, donnée en langage naturel (souvent à l'oral, parfois approximative). Modifie le moment "
    "pour la suivre, sans rien changer d'autre. Réponds uniquement par du JSON : le moment complet, au même format, "
    f"{MOMENT_FORMAT}, avec en plus : \"reply\" (une phrase courte, en français, qui dit ce que tu as changé), "
    "\"outfits\" ({\"Nom\": \"tenue\"} seulement si le joueur change une tenue : une tenue existante du personnage, "
    "nom exact), \"new_outfit\" (null, ou {\"character\": \"...\", \"name\": \"...\", \"description\": \"...\"} si la "
    "tenue demandée n'existe pas encore ; description : les vêtements seuls), et \"cap\" (vide, ou une indication "
    "qui vaut aussi pour la suite de l'histoire, en une phrase). Une posture, un geste, un cadrage ou un point de vue "
    "demandés vont dans image.shot, image.framing et image.viewpoint ; si l'image doit changer, image.keep vaut false.")

DIRECT_IMAGE = (
    "Tu es l'assistant de mise en scène d'un jeu de rôle en roman visuel. Le joueur regarde une image de son "
    "histoire et dit en langage naturel (souvent à l'oral, parfois approximative) ce qui doit changer. Réponds "
    "uniquement par du JSON : {\"reply\": \"...\", \"shot\": \"...\", \"framing\": \"...\", \"viewpoint\": \"...\", "
    "\"visible\": [\"...\"], \"outfits\": {}, \"new_outfit\": null, \"prompt\": \"...\", \"lines\": [], \"cap\": \"\"}. "
    "Ne remplis que ce qui change, laisse vide (ou null) le reste. "
    "shot : la nouvelle description de ce que l'on voit, en français, une phrase (cadrage, posture, geste, "
    f"expression, décor, lumière). framing : un de {', '.join(SC.FRAMINGS)}. viewpoint : un point de vue du lieu "
    "(nom exact), ou « (lieu) » pour le lieu lui-même. visible : les personnages visibles. outfits : "
    "{\"Nom\": \"tenue existante\"}. new_outfit : {\"character\", \"name\", \"description\"} si la tenue demandée "
    "n'existe pas. prompt : le prompt d'image réécrit en anglais pour suivre la demande, en gardant ses renvois aux "
    "images de référence (« image 1 »…) ; seulement si un prompt existe et que seuls la posture, le geste, "
    "l'expression ou la lumière changent. lines : [{\"n\": numéro, \"text\": \"...\"}] si une réplique de cette image "
    "doit changer. cap : une indication qui vaut aussi pour la suite de l'histoire, sinon vide. reply : une phrase "
    "courte, en français, qui dit ce que tu as changé.")


def _wanted_outfits(raw: dict, assets: dict) -> tuple[dict, dict | None]:
    """Tenues demandées par le metteur en scène : celles qui existent, et au plus une tenue à créer."""
    cast = {c["name"]: c for c in _cast(assets)}
    found = {}
    for char, outfit in (raw.get("outfits") or {}).items() if isinstance(raw.get("outfits"), dict) else []:
        name = next((n for n in cast if _same(n, char)), None)
        real = next((o for o in cast[name]["outfits"] if _same(o, outfit)), None) if name else None
        if real:
            found[name] = real
    new = raw.get("new_outfit") if isinstance(raw.get("new_outfit"), dict) else None
    if new:
        name = next((n for n in cast if _same(n, new.get("character"))), None)
        outfit = _one_line(new.get("name"))
        if not name or not outfit:
            new = None
        else:
            existing = next((o for o in cast[name]["outfits"] if _same(o, outfit)), None)
            if existing:
                found[name], new = existing, None
            else:
                new = {"aid": cast[name]["aid"], "character": name, "name": outfit,
                       "description": _one_line(new.get("description"))}
    return found, new


def _create_outfit(new: dict | None) -> dict:
    if not new:
        return {}
    create_outfit(new["aid"], new["name"], new["description"], [])
    return {new["character"]: new["name"]}


def _wearing(outfits: dict) -> str:
    return " ".join(f"{c} porte sa tenue « {o} »." for c, o in outfits.items())


def direct(sid: str | None, instruction: str, proposal: dict | None = None, pid: str | None = None) -> dict:
    """Consigne du joueur en langage naturel : elle s'applique au moment proposé, à une image déjà faite,
    ou, sans rien en cours, guide le moment suivant."""
    instruction = _one_line(instruction)
    if not instruction:
        raise ValueError("Dites ou écrivez ce qui doit changer")
    if proposal:
        return _direct_moment(sid, instruction, proposal)
    if sid and pid:
        return _direct_image(sid, pid, instruction)
    return {"proposal": propose_next(sid, instruction), "reply": "Le récit suit votre indication."}


def _direct_moment(sid: str | None, instruction: str, proposal: dict) -> dict:
    st, assets = _snapshot(sid)
    current = {k: proposal.get(k) for k in ("voix_off", "speaker", "text", "present", "location", "image", "choices")}
    user = (_context(st, assets, sid) + "\nMoment proposé : " + json.dumps(current, ensure_ascii=False)
            + f"\nIndication du joueur : {instruction}")
    raw = llm.extract_json(llm.complete_task("dialogue", DIRECT_MOMENT, user, appsettings.provider("text")))
    found, new = _wanted_outfits(raw if isinstance(raw, dict) else {}, assets)
    moment = normalize_moment(raw, st, assets, sid)
    found.update(_create_outfit(new))
    moment["outfits"] = {**(proposal.get("outfits") or {}), **found}
    if found:  # la tenue change : l'image aussi, et la description le dit (la continuité le comprend)
        moment["image"]["keep"] = False
        moment["image"]["shot"] = _one_line(f"{moment['image']['shot']} {_wearing(found)}")
    if _one_line(raw.get("cap")):
        with S.LOCK:
            st = S.load()
            _remember(st, sid, raw["cap"])
            S.save(st)
    reply = _one_line(raw.get("reply")) or "C'est fait."
    return {"proposal": moment, "reply": reply + (f" Nouvelle tenue : {new['name']}." if new else "")}


def _plan_span(sc: dict, pid: str) -> tuple[int, int]:
    plans = _ordered_plans(sc)
    k = next(i for i, p in enumerate(plans) if p["id"] == pid)
    end = plans[k + 1]["from_line"] if k + 1 < len(plans) else len(sc.get("dialogue", []))
    return plans[k]["from_line"], end


def _direct_image(sid: str, pid: str, instruction: str) -> dict:
    st, assets = _snapshot(sid)
    sc = _find_scene(st, sid)
    _, plan = _find_plan(sc, pid)
    start, end = _plan_span(sc, pid)
    shot = plan.get("shot") or {}
    view = assets.get(plan.get("viewpoint") or "", {}).get("name") or "(lieu)"
    old_prompt = (assets.get(plan["asset"]) or {}).get("prompt", "")
    lines = sc.get("dialogue", [])[start:end]
    user = (_context(st, assets, sid)
            + f"\nImage : {shot.get('note') or '(sans description)'}"
            + f"\nCadrage : {shot.get('framing') or '(libre)'} ; point de vue : {view}"
            + f"\nPersonnages visibles : {', '.join(SC.plan_characters(sc, plan)) or 'personne'}"
            + f"\nPrompt actuel : {old_prompt or '(aucun)'}"
            + "\nRépliques de cette image :\n" + ("\n".join(f"{n}. {l['speaker']} : {l['text']}"
                                                         for n, l in enumerate(lines, 1)) or "(aucune)")
            + f"\nIndication du joueur : {instruction}")
    raw = llm.extract_json(llm.complete_task("dialogue", DIRECT_IMAGE, user, appsettings.provider("text")))
    raw = raw if isinstance(raw, dict) else {}
    found, new = _wanted_outfits(raw, assets)
    found.update(_create_outfit(new))
    _own_image(sid, pid)  # une image gardée d'un autre moment : la modifier ne doit pas changer l'autre

    changed, refs_changed = [], False
    with S.LOCK:
        st = S.load()
        sc = _find_scene(st, sid)
        _, plan = _find_plan(sc, pid)
        cast = {c["name"] for c in _cast(assets)}
        note = _one_line(raw.get("shot"))
        if found:
            for char, outfit in found.items():
                sc.setdefault("outfits", {})[char] = outfit
            note = _one_line(f"{note or (plan.get('shot') or {}).get('note', '')} {_wearing(found)}")
            refs_changed = True
            changed.append("tenue")
        shot = dict(plan.get("shot") or {"framing": "", "angle": "", "note": ""})
        if note and note != shot.get("note"):
            shot["note"] = note
            changed.append("description")
        if raw.get("framing") in SC.FRAMINGS and raw["framing"] != shot.get("framing"):
            shot["framing"] = raw["framing"]
            changed.append("cadrage")
        plan["shot"] = shot
        if _one_line(raw.get("viewpoint")):
            wanted = _one_line(raw["viewpoint"])
            to_location = S.norm(wanted).strip("()« »") == "lieu"  # « (lieu) » : le lieu lui-même
            aid = "" if to_location else _viewpoint_aid(assets, sc.get("location"), wanted)
            if (aid or to_location) and aid != (plan.get("viewpoint") or ""):
                if aid:
                    plan["viewpoint"] = aid
                else:
                    plan.pop("viewpoint", None)
                refs_changed = True
                changed.append("point de vue")
        visible = [n for n in raw.get("visible") or [] if n in cast] if isinstance(raw.get("visible"), list) else []
        if visible and visible != SC.plan_characters(sc, plan):
            for name in visible:
                if name not in sc.setdefault("characters", []):
                    sc["characters"].append(name)
            plan["characters"] = list(dict.fromkeys(visible))
            refs_changed = True
            changed.append("personnages")
        for item in raw.get("lines") or [] if isinstance(raw.get("lines"), list) else []:
            try:
                n = int(item.get("n")) - 1
            except (TypeError, ValueError, AttributeError):
                continue
            text = _one_line(item.get("text"))
            if 0 <= n < end - start and text:
                sc["dialogue"][start + n]["text"] = text
                changed.append("réplique")
        if _one_line(raw.get("cap")):
            _remember(st, sid, raw["cap"])
        S.save(st)

    # Le prompt suit : réécrit par le modèle si seules la pose ou l'expression changent, sinon rédigé de
    # nouveau (les images de référence et leur numéro ont changé).
    new_prompt = None
    image_changed = any(c != "réplique" for c in changed)
    if image_changed:
        rewritten = _one_line(raw.get("prompt"))
        if rewritten and old_prompt and not refs_changed:
            new_prompt = PR.with_style(PR.clean(rewritten), PR.llm_style())
        elif old_prompt:  # sans prompt, il sera rédigé au moment du dessin
            st, assets_data = _snapshot(sid)
            sc = _find_scene(st, sid)
            k, _ = _find_plan(sc, pid)
            new_prompt = SC.suggest(st, {"assets": assets_data}, sc, k)
        with S.LOCK:
            asset = _find_plan(_find_scene(S.load(), sid), pid)[1]["asset"]
        with A.LOCK:
            data = A.load()
            if asset in data["assets"]:
                data["assets"][asset]["prompt"] = new_prompt or ""
                A.save(data)
    reply = _one_line(raw.get("reply")) or ("C'est fait." if changed else "Rien n'a changé.")
    return {"reply": reply + (f" Nouvelle tenue : {new['name']}." if new else ""), "changed": changed,
            "prompt": new_prompt, "redraw": image_changed, "scene": sid, "plan": pid}


# ----- vue -----------------------------------------------------------------------------------------------

def view() -> dict:
    """La vue de l'atelier (personnages, lieux, scènes, images), avec ce que le récit ajoute : la ligne vécue,
    l'état de chaque scène et la carte des lignes de vie."""
    out = FA.view()
    with S.LOCK:
        st = S.load()
    with A.LOCK:
        assets = A.load()["assets"]
    rc = st.get("recit") or {}
    ids = {sc["id"] for sc in S.all_scenes(st)}
    current = rc.get("current") if rc.get("current") in ids else _default_current(st)
    pending = rc.get("pending") or {}
    if not pending or pending.get("scene") != current or not is_open(st, _find_scene(st, current)):
        pending = None
    out["recit"] = {
        "pending": pending,
        "ambiance": rc.get("ambiance", ""),
        "ambiances": list(AMBIANCES),
        "auto_draw": bool(rc.get("auto_draw")),
        "current": current,
        "path": path_to(st, current) if current else [],
        "scenes": {sc["id"]: {"open": is_open(st, sc), "ending": bool(sc.get("ending")),
                              "next": _successor(st, sc), "choices": sc.get("choices") or [],
                              "route_of": sc.get("route_of"), "return_to": sc.get("return_to"),
                              "outfits": sc.get("outfits") or {}, "directions": sc.get("directions") or [],
                              "plans": {p["id"]: {"framing": (p.get("shot") or {}).get("framing", ""),
                                                  "shared": _shares_image(st, p)} for p in sc.get("plans", [])}}
                   for sc in S.all_scenes(st)},
        "graph": SG.build(st),
        "can_undo": bool(rc.get("last")) and (rc.get("last") or {}).get("scene") == current,
        "framings": list(SC.FRAMINGS),
        "wardrobe": {c["name"]: c["outfits"] for c in _cast(assets)},
    }
    return out


def route(method: str, path: str, body: dict) -> dict:
    if method == "GET" and path.rstrip("/") == "/api/recit":
        return view()
    if method == "POST":
        routes = {
            "/api/recit/frame": lambda: set_frame(body.get("title", ""), body.get("idea", ""),
                                                  body.get("ambiance", ""), body.get("style") or None),
            "/api/recit/options": lambda: set_options(body),
            "/api/recit/propose": lambda: propose_next(body.get("scene") or None, body.get("instruction", ""),
                                                       body.get("previous")),
            "/api/recit/direct": lambda: direct(body.get("scene") or None, body.get("instruction", ""),
                                                body.get("proposal"), body.get("plan") or None),
            "/api/recit/moment": lambda: commit_moment(body.get("scene") or None, body.get("moment") or {}),
            "/api/recit/undo": undo_last,
            "/api/recit/choices/propose": lambda: propose_choices(body["scene"]),
            "/api/recit/choose": lambda: choose(body["scene"], body.get("options") or [], int(body.get("picked", 0))),
            "/api/recit/branch": lambda: branch_after(body["scene"], int(body["line"]), body.get("label", "")),
            "/api/recit/rejoin": lambda: rejoin(body["scene"], body["target"], int(body.get("line") or 0)),
            "/api/recit/finish": lambda: finish(body["scene"]),
            "/api/recit/reopen": lambda: reopen(body["scene"]),
            "/api/recit/current": lambda: set_current(body["scene"], bool(body.get("follow"))),
            "/api/recit/label": lambda: set_label(body["scene"], body["target"], body.get("label", "")),
            "/api/recit/outfit": lambda: set_outfit(body["scene"], body.get("character", ""), body.get("outfit", "")),
            "/api/recit/shot": lambda: set_shot(body["scene"], body["plan"], body.get("note"), body.get("framing"),
                                                body.get("viewpoint"), body.get("characters")),
            "/api/recit/draw": lambda: draw(body["scene"], body["plan"], body.get("prompt")),
        }
        if path in routes:
            return routes[path]()
    raise NotFound("introuvable")
