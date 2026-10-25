"""Carte de l'histoire : les scènes reliées entre elles.

Une scène mène à la suivante de l'histoire, sauf si elle a des choix (carrefour) ou si elle est une fin.
Une route est un chemin du début de l'histoire jusqu'à une fin ou une impasse. Les routes ne sont pas
stockées : elles se déduisent des choix, donc elles restent justes quand on modifie la carte.
"""

from __future__ import annotations

from renpy_maker import story as S

MAX_ROUTES = 30  # au-delà, la carte ne liste plus les routes (il y en a trop pour les lire)


def _ordered_scenes(st: dict) -> list[tuple[int, dict]]:
    return [(ci, sc) for ci, ch in enumerate(st.get("chapters", [])) for sc in ch.get("scenes", [])]


def build(st: dict) -> dict:
    scenes = _ordered_scenes(st)
    ids = [sc["id"] for _, sc in scenes]
    successor = {ids[i]: ids[i + 1] for i in range(len(ids) - 1)}
    nodes, edges = [], []
    for ci, sc in scenes:
        sid = sc["id"]
        choices = sc.get("choices") or []
        # Suite explicite (rattachement d'une route), sinon la scène suivante dans l'ordre du chapitre.
        nxt = sc.get("next") or successor.get(sid)
        # Pas de suite : c'est la fin de l'histoire, même si elle n'est pas marquée comme fin.
        ending = bool(sc.get("ending")) or (not choices and not nxt)
        nodes.append({"id": sid, "title": sc.get("title", ""), "chapter": ci + 1,
                      "ending": ending, "has_text": bool(sc.get("dialogue"))})
        if choices:
            edges += [{"source": sid, "target": c["target"], "label": c.get("label", ""), "kind": "choice"}
                      for c in choices]
        elif not ending and nxt:
            edges.append({"source": sid, "target": nxt, "label": "", "kind": "next"})

    known = set(ids)
    out = {n["id"]: [] for n in nodes}
    for e in edges:
        if e["target"] in known:
            out[e["source"]].append(e["target"])

    start = ids[0] if ids else None
    depth = _depths(start, out)
    for n in nodes:
        n["depth"] = depth.get(n["id"])
        n["reachable"] = n["id"] in depth
    dead_ends = [n["id"] for n in nodes if not n["ending"] and not out[n["id"]]]
    routes = _routes(start, out, {n["id"] for n in nodes if n["ending"]})
    return {
        "start": start,
        "nodes": nodes,
        "edges": edges,
        "routes": routes,
        "routes_truncated": len(routes) >= MAX_ROUTES,
        "problems": ([f"Scène inatteignable : {n['title'] or n['id']}" for n in nodes if not n["reachable"]]
                     + [f"Impasse, ni fin ni suite : {_title(nodes, s)}" for s in dead_ends]),
    }


def _title(nodes: list[dict], sid: str) -> str:
    return next((n["title"] or sid for n in nodes if n["id"] == sid), sid)


def _depths(start: str | None, out: dict[str, list[str]]) -> dict[str, int]:
    """Distance de chaque scène depuis le début (en nombre de choix ou de scènes)."""
    if start is None:
        return {}
    depth = {start: 0}
    frontier = [start]
    while frontier:
        nxt = []
        for sid in frontier:
            for t in out.get(sid, []):
                if t not in depth:
                    depth[t] = depth[sid] + 1
                    nxt.append(t)
        frontier = nxt
    return depth


def _routes(start: str | None, out: dict[str, list[str]], endings: set[str]) -> list[dict]:
    """Chemins du début jusqu'à une fin ou une impasse, sans boucle. Limité à MAX_ROUTES."""
    if start is None:
        return []
    found: list[dict] = []

    def walk(sid: str, path: list[str]) -> None:
        if len(found) >= MAX_ROUTES:
            return
        nexts = [t for t in out.get(sid, []) if t not in path]
        if not nexts:
            found.append({"path": list(path), "end": sid, "ending": sid in endings})
            return
        for t in nexts:
            walk(t, path + [t])

    walk(start, [start])
    return found


MAX_CHOICES = 4   # au-delà, le choix n'est plus lisible sur un écran de jeu
MAX_LABEL = 60


def find_scene(st: dict, sid: str) -> tuple[dict, dict]:
    """(chapitre, scène) d'une scène de l'histoire."""
    for ch in st.get("chapters", []):
        for sc in ch.get("scenes", []):
            if sc["id"] == sid:
                return ch, sc
    raise ValueError(f"Scène inconnue : {sid}")


def _next_scene_id(st: dict) -> str:
    numbers = [int(sc["id"][1:]) for _, sc in _ordered_scenes(st) if sc["id"][1:].isdigit() and sc["id"][0] == "s"]
    return f"s{max(numbers, default=0) + 1}"


def set_choices(st: dict, sid: str, items: list[dict]) -> list[str]:
    """Remplace les chemins d'une scène. Chaque élément : {label, target} (scène existante) ou
    {label, new: {title, summary}} (nouvelle scène créée juste après la scène de départ).
    Liste vide : la scène retrouve son passage automatique vers la suivante. Renvoie les identifiants créés."""
    if len(items) > MAX_CHOICES:
        raise ValueError(f"Au plus {MAX_CHOICES} chemins par scène")
    ch, sc = find_scene(st, sid)
    known = {s["id"] for _, s in _ordered_scenes(st)}
    targets: list[str] = []
    created: list[str] = []
    resolved: list[dict] = []
    insert_at = ch["scenes"].index(sc) + 1
    for it in items:
        label = " ".join(str(it.get("label", "")).split())
        if not label:
            raise ValueError("Chaque chemin a besoin d'un libellé")
        if len(label) > MAX_LABEL:
            raise ValueError(f"Libellé trop long (au plus {MAX_LABEL} caractères)")
        if it.get("new") is not None:
            title = " ".join(str(it["new"].get("title", "")).split())
            if not title:
                raise ValueError("La nouvelle scène a besoin d'un titre")
            new_id = _next_scene_id(st)
            new = S.add_scene(ch, new_id, title, str(it["new"].get("summary", "")).strip(),
                              list(sc.get("characters", [])), sc.get("location"), dict(sc.get("outfits") or {}))
            ch["scenes"].pop()                      # add_scene ajoute en fin : on la range juste après
            ch["scenes"].insert(insert_at, new)
            insert_at += 1
            known.add(new_id)
            created.append(new_id)
            target = new_id
        else:
            target = it.get("target", "")
            if target not in known:
                raise ValueError(f"Cible inconnue : {target or '(vide)'}")
            if target == sid:
                raise ValueError("Un chemin ne peut pas revenir sur la même scène")
        if target in targets:
            raise ValueError("Deux chemins mènent à la même scène")
        targets.append(target)
        resolved.append({"target": target, "label": label})

    sc["choices"] = resolved
    if resolved:
        sc["ending"] = False  # une scène avec des chemins n'est plus une fin
    ch["scene_count"] = len(ch["scenes"])
    st["map_validated"] = False                     # la carte a changé : à revalider
    return created


def start_route(st: dict, sid: str, plan_id: str, label: str, title: str) -> str:
    """Commence une route à partir d'une image : la suite (images et répliques à partir de cette image)
    passe dans une nouvelle scène, et la scène de départ garde un choix vers elle.
    Renvoie l'identifiant de la nouvelle scène. La partie commune reste dans la scène de départ."""
    label = " ".join(str(label).split())
    title = " ".join(str(title).split())
    if not label:
        raise ValueError("Le choix a besoin d'un libellé")
    if len(label) > MAX_LABEL:
        raise ValueError(f"Libellé trop long (au plus {MAX_LABEL} caractères)")
    if not title:
        raise ValueError("La route a besoin d'un titre")
    ch, sc = find_scene(st, sid)
    ordered = sorted(sc.get("plans", []), key=lambda p: (p["from_line"], 0 if p.get("pause") else 1))
    ids = [p["id"] for p in ordered]
    if plan_id not in ids:
        raise ValueError("Image inconnue dans cette scène")
    pos = ids.index(plan_id)
    if pos == 0:
        raise ValueError("Le choix doit venir après au moins une image de la scène")
    cut = ordered[pos]["from_line"]
    tail_ids = set(ids[pos:])
    dialogue = sc.get("dialogue", [])

    new_id = _next_scene_id(st)
    new = S.add_scene(ch, new_id, title, "", list(sc.get("characters", [])), sc.get("location"),
                      dict(sc.get("outfits") or {}))
    ch["scenes"].pop()
    ch["scenes"].insert(ch["scenes"].index(sc) + 1, new)

    # La suite : répliques et images à partir du point de coupe, numérotées depuis le début de la route.
    new["dialogue"] = dialogue[cut:]
    new["plans"] = []
    for p in sc.get("plans", []):
        if p["id"] in tail_ids:
            moved = dict(p)
            moved["from_line"] = p["from_line"] - cut
            new["plans"].append(moved)
    tags = sc.get("line_tags") or {}
    new["line_tags"] = {str(int(k) - cut): v for k, v in tags.items() if int(k) >= cut}

    # La scène de départ s'arrête au choix. Ce qui terminait la scène (choix, fin) suit la route.
    sc["dialogue"] = dialogue[:cut]
    sc["plans"] = [p for p in sc.get("plans", []) if p["id"] not in tail_ids]
    sc["line_tags"] = {k: v for k, v in tags.items() if int(k) < cut}
    new["choices"], sc["choices"] = sc.get("choices") or [], [{"target": new_id, "label": label}]
    new["ending"], sc["ending"] = sc.get("ending", False), False
    new["route_of"] = sid
    ch["scene_count"] = len(ch["scenes"])
    st["map_validated"] = False
    return new_id


def route_from(st: dict, sid: str) -> str | None:
    """Scène d'origine d'une route, ou None. Une route est reliée par un seul choix, venu de la scène
    qui la précède dans le chapitre (ou, pour une route récente, marquée à sa création)."""
    ordered = _ordered_scenes(st)
    ids = [sc["id"] for _, sc in ordered]
    if sid not in ids:
        return None
    _, sc = find_scene(st, sid)
    source = sc.get("route_of")
    if source and source in ids and any(c["target"] == sid for c in find_scene(st, source)[1].get("choices") or []):
        return source
    incoming = [s["id"] for _, s in ordered for c in s.get("choices") or [] if c["target"] == sid]
    if len(set(incoming)) == 1 and ids.index(incoming[0]) == ids.index(sid) - 1:
        return incoming[0]
    return None


def undo_route(st: dict, sid: str) -> str:
    """Remet la route dans la scène d'origine : répliques, images et choix reviennent à la suite,
    et la scène de la route disparaît. Renvoie l'identifiant de la scène d'origine."""
    source_id = route_from(st, sid)
    if source_id is None:
        raise ValueError("Cette scène n'est pas une route")
    ch, route = find_scene(st, sid)
    _, src = find_scene(st, source_id)
    others = [s["id"] for _, s in _ordered_scenes(st) if s["id"] not in (sid, source_id)
              and any(c["target"] == sid for c in s.get("choices") or [])]
    if others:
        raise ValueError("Une autre scène mène aussi à cette route : impossible de l'annuler")

    offset = len(src.get("dialogue", []))
    src["dialogue"] = list(src.get("dialogue", [])) + list(route.get("dialogue", []))
    used = {p["id"] for p in src.get("plans", [])}
    for p in route.get("plans", []):
        moved = dict(p)
        moved["from_line"] = p["from_line"] + offset
        if moved["id"] in used:
            n = 1
            while f"p{n}" in used:
                n += 1
            moved["id"] = f"p{n}"
        used.add(moved["id"])
        src.setdefault("plans", []).append(moved)
    tags = src.setdefault("line_tags", {})
    for k, v in (route.get("line_tags") or {}).items():
        tags[str(int(k) + offset)] = v

    kept = [c for c in src.get("choices") or [] if c["target"] != sid and c["target"] != source_id]
    src["choices"] = kept + [c for c in route.get("choices") or [] if c["target"] != source_id]
    src["ending"] = bool(route.get("ending"))
    for _, s in _ordered_scenes(st):  # les routes de la route suivent leur nouvelle origine
        if s.get("route_of") == sid:
            s["route_of"] = source_id

    ch["scenes"].remove(route)
    ch["scene_count"] = len(ch["scenes"])
    st["map_validated"] = False
    return source_id



def _successor(st: dict, sid: str) -> str | None:
    ids = [sc["id"] for _, sc in _ordered_scenes(st)]
    i = ids.index(sid)
    return ids[i + 1] if i + 1 < len(ids) else None


def _insert_after(st: dict, ch: dict, after: dict, title: str, summary: str, src: dict) -> dict:
    """Nouvelle scène vide, qui reprend personnages, lieu et tenues de la scène source, juste après `after`."""
    new = S.add_scene(ch, _next_scene_id(st), title, summary, list(src.get("characters", [])),
                      src.get("location"), dict(src.get("outfits") or {}))
    ch["scenes"].pop()
    ch["scenes"].insert(ch["scenes"].index(after) + 1, new)
    return new


def _move_content(sc: dict, cut: int, ids_to_move: set[str], dst: dict) -> None:
    """Déplace répliques et images à partir de `cut` (et les images nommées) de sc vers dst."""
    dialogue = sc.get("dialogue", [])
    tags = sc.get("line_tags") or {}
    dst["dialogue"] = dialogue[cut:]
    dst["plans"] = []
    for p in sc.get("plans", []):
        if p["id"] in ids_to_move:
            moved = dict(p)
            moved["from_line"] = p["from_line"] - cut
            dst["plans"].append(moved)
    dst["line_tags"] = {str(int(k) - cut): v for k, v in tags.items() if int(k) >= cut}
    sc["dialogue"] = dialogue[:cut]
    sc["plans"] = [p for p in sc.get("plans", []) if p["id"] not in ids_to_move]
    sc["line_tags"] = {k: v for k, v in tags.items() if int(k) < cut}


def _branch(sc: dict, old_next: str | None, label: str, target: str) -> None:
    """Ajoute un choix à une scène. Si elle n'en avait pas, son passage vers la suite devient le choix « Continuer »
    (la suite reste jouable, même sans choix visible)."""
    if not sc.get("choices"):
        sc["choices"] = [{"target": old_next, "label": "Continuer"}] if old_next else []
    sc["choices"] = [c for c in sc["choices"] if c["target"] != target] + [{"target": target, "label": label}]
    sc["next"] = None
    sc["ending"] = False


def _check_text(label: str, title: str) -> tuple[str, str]:
    label = " ".join(str(label).split())
    title = " ".join(str(title).split())
    if not label:
        raise ValueError("Le chemin a besoin d'un libellé")
    if len(label) > MAX_LABEL:
        raise ValueError(f"Libellé trop long (au plus {MAX_LABEL} caractères)")
    if not title:
        raise ValueError("La route a besoin d'un titre")
    return label, title


def branch_at(st: dict, sid: str, plan_id: str, label: str, title: str) -> str:
    """Bifurcation à une image : la scène s'arrête avant cette image ; la suite (images et répliques à partir
    d'ici) reste la partie commune, reliée par « Continuer » ; la route est une nouvelle ligne vide, à remplir.
    Renvoie l'identifiant de la route."""
    label, title = _check_text(label, title)
    ch, sc = find_scene(st, sid)
    ordered = sorted(sc.get("plans", []), key=lambda p: (p["from_line"], 0 if p.get("pause") else 1))
    ids = [p["id"] for p in ordered]
    if plan_id not in ids:
        raise ValueError("Image inconnue dans cette scène")
    pos = ids.index(plan_id)
    if pos == 0:
        raise ValueError("La bifurcation doit venir après au moins une image")
    old_next = sc.get("next") or _successor(st, sid)
    common = _insert_after(st, ch, sc, sc["title"] + " (suite)", "", sc)
    _move_content(sc, ordered[pos]["from_line"], set(ids[pos:]), common)
    common["choices"], sc["choices"] = sc.get("choices") or [], []
    common["ending"], sc["ending"] = bool(sc.get("ending")), False
    common["next"] = old_next if not common["choices"] else None
    route = _insert_after(st, ch, common, title, "", sc)
    route["next"] = old_next
    route["route_of"] = sid
    _branch(sc, common["id"], label, route["id"])
    ch["scene_count"] = len(ch["scenes"])
    st["map_validated"] = False
    return route["id"]


def rejoin(st: dict, sid: str, target: str) -> None:
    """La scène continue vers `target` (par exemple la suite de l'histoire) quand elle n'a pas de chemins."""
    _, sc = find_scene(st, sid)
    if target == sid or target not in {s["id"] for _, s in _ordered_scenes(st)}:
        raise ValueError("Scène d'arrivée inconnue")
    if sc.get("choices"):
        raise ValueError("Cette scène a des chemins : elle ne peut pas être rattachée directement")
    sc["next"] = target
    sc["ending"] = False
    st["map_validated"] = False


def detach(st: dict, sid: str) -> dict:
    """Retire une route : son contenu va dans la réserve (réutilisable) et le chemin qui y menait disparaît."""
    ch, sc = find_scene(st, sid)
    if sc.get("choices"):
        raise ValueError("Retirez d'abord les chemins qui partent de cette scène")
    block = {"id": f"r{len(st.get('reserve', [])) + 1}", "title": sc.get("title", ""),
             "summary": sc.get("summary", ""), "characters": list(sc.get("characters", [])),
             "location": sc.get("location"), "outfits": dict(sc.get("outfits") or {}),
             "dialogue": sc.get("dialogue", []), "plans": sc.get("plans", []),
             "line_tags": sc.get("line_tags") or {}, "next": sc.get("next"), "ending": bool(sc.get("ending"))}
    st.setdefault("reserve", []).append(block)
    for _, other in _ordered_scenes(st):
        remaining = [c for c in other.get("choices") or [] if c["target"] != sid]
        if len(remaining) != len(other.get("choices") or []):
            other["choices"] = remaining
            if len(remaining) == 1:  # un seul chemin qui reste : c'est simplement la suite
                other["next"] = remaining[0]["target"]
                other["choices"] = []
    ch["scenes"].remove(sc)
    ch["scene_count"] = len(ch["scenes"])
    st["map_validated"] = False
    return block


def attach(st: dict, source_sid: str, block_id: str, label: str) -> str:
    """Rattache un bloc de la réserve à une scène, par un chemin. Renvoie l'identifiant de la nouvelle scène."""
    label, _ = _check_text(label, "x")
    block = next((b for b in st.get("reserve", []) if b["id"] == block_id), None)
    if block is None:
        raise ValueError("Ce contenu n'est plus dans la réserve")
    ch, sc = find_scene(st, source_sid)
    old_next = sc.get("next") or _successor(st, source_sid)
    new = _insert_after(st, ch, sc, block["title"], block.get("summary", ""), block)
    new["characters"] = list(block.get("characters", []))
    new["dialogue"] = list(block.get("dialogue", []))
    new["plans"] = [dict(p) for p in block.get("plans", [])]
    new["line_tags"] = dict(block.get("line_tags") or {})
    new["next"] = block.get("next")
    new["ending"] = bool(block.get("ending"))
    new["route_of"] = source_sid
    _branch(sc, old_next, label, new["id"])
    st["reserve"].remove(block)
    ch["scene_count"] = len(ch["scenes"])
    st["map_validated"] = False
    return new["id"]
