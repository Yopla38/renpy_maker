"""Interface locale de construction du registre d'actifs.

Lancement :
    python3 webapp/server.py            # puis ouvrir http://127.0.0.1:8765

Écoute uniquement sur 127.0.0.1. Le jeton Replicate est lu dans l'environnement, ou, à
défaut, dans ~/.config/slapsci/llm_api_keys.txt. Il n'est jamais renvoyé au navigateur.
"""

from __future__ import annotations

import json
import mimetypes
import os
import re
import sys
import threading
import traceback
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import assets as A  # noqa: E402
import plan as P  # noqa: E402
import prompts as PR  # noqa: E402
import scenes as SC  # noqa: E402
import renpy_export as RE  # noqa: E402
from prompts import match_asset as _match_asset  # noqa: E402
import story as S  # noqa: E402

HOST, PORT = "127.0.0.1", 8765
KEYFILE = Path.home() / ".config/slapsci/llm_api_keys.txt"
INDEX = Path(__file__).with_name("index.html")
PLAN_PAGE = Path(__file__).with_name("plan.html")

_lock = threading.Lock()          # protège game_spec/assets.yaml
_slock = threading.Lock()         # protège game_spec/story.yaml
_jobs: dict[str, dict] = {}       # job_id -> {state, message, candidate}


def _load_token_from_keyfile() -> None:
    """Charge REPLICATE_API_TOKEN depuis le fichier de clés, si absent de l'environnement."""
    if os.environ.get("REPLICATE_API_TOKEN") or not KEYFILE.exists():
        return
    for line in KEYFILE.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^\s*(?:export\s+)?REPLICATE_API_TOKEN\s*=\s*(.+?)\s*$", line)
        if m:
            os.environ["REPLICATE_API_TOKEN"] = m.group(1).strip("'\"")
            return


def _snapshot() -> dict:
    with _lock:
        data = A.load()
    return data


def _asset_view(aid: str, a: dict) -> dict:
    return {
        "id": aid,
        "kind": a["kind"],
        "name": a.get("name", ""),
        "description": a.get("description", ""),
        "prompt": a.get("prompt", ""),
        "parent": a.get("parent"),
        "status": a["status"],
        "validated_candidate": a.get("validated_candidate"),
        "candidates": [
            {"index": i, **c, "url": "/files/" + c["file"]}
            for i, c in enumerate(a.get("candidates", []))
        ],
    }


class Handler(BaseHTTPRequestHandler):
    server_version = "renpy_maker/0.1"

    # ----- utilitaires -----
    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code: int, obj) -> None:
        self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

    def _body(self) -> dict:
        n = int(self.headers.get("Content-Length", "0") or 0)
        return json.loads(self.rfile.read(n) or b"{}")

    def log_message(self, fmt, *args):  # journal court sur stderr
        sys.stderr.write("%s %s\n" % (self.command, self.path))

    # ----- GET -----
    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/":
            return self._send(200, INDEX.read_bytes(), "text/html; charset=utf-8")
        if path in ("/histoire", "/histoire/"):
            return self._send(200, PLAN_PAGE.read_bytes(), "text/html; charset=utf-8")
        if path == "/api/assets":
            data = _snapshot()
            return self._json(200, {"assets": [_asset_view(k, v) for k, v in data["assets"].items()]})
        if path == "/api/story":
            with _slock:
                return self._json(200, _story_view())
        if path == "/api/renpy":
            return self._renpy_view()
        if path == "/api/story/elements":
            return self._elements()
        if path == "/api/story/scene-status":
            with _slock:
                st = S.load()
            return self._json(200, {"scenes": SC.scene_status(st, A.load()["assets"])})
        if path == "/api/style":
            return self._json(200, A.reference_style())
        if path.startswith("/api/jobs/"):
            job = _jobs.get(path.rsplit("/", 1)[-1])
            return self._json(200, job) if job else self._json(404, {"error": "job inconnu"})
        if path.startswith("/files/assets/"):
            return self._file(path[len("/files/"):])
        self._json(404, {"error": "introuvable"})

    def _file(self, rel: str) -> None:
        base = (ROOT / "assets").resolve()
        target = (ROOT / rel).resolve()
        if base not in target.parents or not target.is_file():
            return self._json(404, {"error": "fichier introuvable"})
        ctype = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        self._send(200, target.read_bytes(), ctype)

    # ----- POST -----
    def do_POST(self):
        path = urlparse(self.path).path
        try:
            body = self._body()
            if path == "/api/asset":
                return self._create_asset(body)
            if path == "/api/generate":
                return self._generate(body)
            if path == "/api/renpy/settings":
                return self._renpy_settings(body)
            if path == "/api/renpy/export":
                return self._renpy_export()
            if path == "/api/renpy/lint":
                return self._json(200, RE.lint())
            if path == "/api/renpy/launch":
                return self._json(200, RE.launch())
            if path in ("/api/story/meta", "/api/story/settings"):
                return self._story_settings(path, body)
            if path == "/api/story/chapter":
                return self._chapter_generate(body)
            if path == "/api/story/elements/create":
                return self._element_create(body)
            m = re.fullmatch(r"/api/story/chapter/(\w+)", path)
            if m:
                return self._chapter_update(m.group(1), body)
            m = re.fullmatch(r"/api/story/chapter/(\w+)/delete", path)
            if m:
                return self._chapter_delete(m.group(1))
            m = re.fullmatch(r"/api/story/chapter/(\w+)/scene/(\w+)/plans", path)
            if m:
                return self._plan_create(m.group(1), m.group(2), body)
            m = re.fullmatch(r"/api/story/chapter/(\w+)/scene/(\w+)/plans/(\w+)/suggest-prompt", path)
            if m:
                return self._plan_suggest(m.group(1), m.group(2), m.group(3), body)
            m = re.fullmatch(r"/api/story/chapter/(\w+)/scene/(\w+)/plans/(\w+)", path)
            if m:
                return self._plan_update(m.group(1), m.group(2), m.group(3), body)
            m = re.fullmatch(r"/api/story/chapter/(\w+)/scene/(\w+)/detect-elements", path)
            if m:
                return self._detect_elements(m.group(1), m.group(2))
            m = re.fullmatch(r"/api/story/chapter/(\w+)/scene/(\w+)/dialogue", path)
            if m:
                return self._dialogue_generate(m.group(1), m.group(2), body)
            m = re.fullmatch(r"/api/story/chapter/(\w+)/scene/(\w+)", path)
            if m:
                return self._scene_update(m.group(1), m.group(2), body)
            m = re.fullmatch(r"/api/asset/([\w-]+)/suggest-prompt", path)
            if m:
                return self._suggest_prompt(m.group(1), body)
            m = re.fullmatch(r"/api/asset/([\w-]+)", path)
            if m:
                return self._update_asset(m.group(1), body)
            m = re.fullmatch(r"/api/asset/([\w-]+)/candidate/(\d+)", path)
            if m:
                return self._set_status(m.group(1), int(m.group(2)), body)
            self._json(404, {"error": "introuvable"})
        except (ValueError, KeyError, IndexError) as e:
            self._json(400, {"error": str(e)})
        except Exception as e:  # erreur inattendue : renvoyée sans trace complète
            traceback.print_exc()
            self._json(500, {"error": f"{type(e).__name__}: {e}"})

    # ----- éléments de l'histoire (personnages, lieux, tenues) -----
    def _elements(self) -> None:
        with _slock:
            st = S.load()
        assets = A.load()["assets"]
        chars = {S.norm(a["name"]): aid for aid, a in assets.items() if a["kind"] == "character"}
        out = []
        for el in S.story_elements(st):
            aid = _match_asset(assets, el, chars)
            a = assets.get(aid) if aid else None
            out.append({**el, "asset_id": aid,
                        "asset_status": a["status"] if a else None,
                        "candidates": len(a["candidates"]) if a else 0})
        self._json(200, {"elements": out})

    def _element_create(self, body: dict) -> None:
        kind = body.get("kind")
        name = str(body.get("name", "")).strip()
        if kind not in A.KINDS or not name:
            raise ValueError("Type et nom requis")
        with _slock:
            st = S.load()
        with _lock:
            data = A.load()
            assets = data["assets"]
            parent = None
            if kind == "outfit":
                pname = S.norm(body.get("parent_name", ""))
                parent = next((aid for aid, a in assets.items()
                               if a["kind"] == "character" and S.norm(a["name"]) == pname), None)
                if parent is None:
                    raise ValueError(f"Créez d'abord le personnage « {body.get('parent_name', '')} »")
            existing = _match_asset(assets, {"kind": kind, "name": name, "parent_name": body.get("parent_name")},
                                    {S.norm(a["name"]): aid for aid, a in assets.items() if a["kind"] == "character"})
            if existing:
                return self._json(200, {"ok": True, "asset_id": existing, "existing": True})
            prefix = {"character": "char", "outfit": "outfit", "location": "loc", "object": "obj", "scene": "scene"}[kind]
            base = f"{prefix}_{_slug(name)}"
            aid, n = base, 2
            while aid in assets:
                aid, n = f"{base}_{n}", n + 1
            A.add_asset(data, aid, kind, name, str(body.get("description", "")), parent)
            warning = None
            try:
                data["assets"][aid]["prompt"] = PR.suggest(st, data, aid)
            except Exception as e:  # le prompt reste vide, l'auteur le rédige ou réessaie
                warning = f"Prompt non proposé automatiquement : {e}"
            A.save(data)
        self._json(200, {"ok": True, "asset_id": aid, "warning": warning})

    def _suggest_prompt(self, aid: str, body: dict) -> None:
        with _slock:
            st = S.load()
        data = A.load()
        if aid not in data["assets"]:
            raise KeyError(f"Actif inconnu : {aid}")
        text = PR.suggest(st, data, aid, body.get("provider") or None)
        self._json(200, {"prompt": text, "warnings": A.english_warnings(text)})

    # ----- export Ren'Py -----
    def _renpy_view(self) -> None:
        with _slock:
            st = S.load()
        data = A.load()
        self._json(200, {
            "settings": RE.settings(st),
            "problems": RE.problems(st, data),
            "scenes": len(S.all_scenes(st)),
            "project_dir": str(RE.project_dir()),
            "sdk_found": RE.renpy_sh().exists(),
        })

    def _renpy_settings(self, body: dict) -> None:
        with _slock:
            st = S.load()
            cur = st["settings"].setdefault("renpy", {})
            if "title" in body:
                cur["title"] = str(body["title"]).strip() or "Mon histoire"
            for k in ("width", "height"):
                if k in body:
                    v = int(body[k])
                    if not 320 <= v <= 7680:
                        raise ValueError(f"{k} hors limites")
                    cur[k] = v
            S.save(st)
        self._renpy_view()

    def _renpy_export(self) -> None:
        with _slock:
            st = S.load()
        result = RE.export(st, A.load())
        self._json(200, result)

    # ----- éléments visuels manquants -----
    def _detect_elements(self, cid: str, sid: str) -> None:
        with _slock:
            st = S.load()
            sc = _find_scene(_find_chapter(st, cid), sid)
        assets = A.load()["assets"]
        found = SC.detect_elements(st, sc, assets)
        declared = {S.norm(c) for c in sc.get("characters", [])}
        for el in found:
            aid = SC.match_registry(el["name"], el["kind"], assets)
            el["exists"] = aid is not None
            el["match"] = assets[aid].get("name", aid) if aid else None
            el["in_scene"] = S.norm(el["name"]) in declared
        self._json(200, {"elements": found})

    # ----- images de scène (plans) -----
    def _plan_create(self, cid: str, sid: str, body: dict) -> None:
        """Ajoute une image à une réplique : nouvelle image vide, ou image déjà existante (asset)."""
        with _slock:
            st = S.load()
            ch = _find_chapter(st, cid)
            sc = _find_scene(ch, sid)
            _guard(ch, sc, {"plans": None})
        if not sc.get("dialogue"):
            raise ValueError("Écrivez d'abord les répliques : les images suivent le dialogue")
        from_line = int(body.get("from_line", 0))
        if not 0 <= from_line < len(sc["dialogue"]):
            raise ValueError("Le début d'image doit être une réplique existante")
        src = body.get("asset")
        candidate = None
        if src:
            data = A.load()
            if src not in data["assets"]:
                raise ValueError("Image inconnue")
            a = data["assets"][src]
            candidate = int(body["candidate"]) if body.get("candidate") is not None else a.get("validated_candidate")
            if candidate is None or not 0 <= candidate < len(a.get("candidates", [])):
                raise ValueError("Choisissez une image générée")
            asset_id = src
        else:
            with _lock:
                data = A.load()
                pid_hint = _next_pid(sc)
                base = f"scene_{sid}_{pid_hint}"
                asset_id, k = base, 2
                while asset_id in data["assets"]:
                    asset_id, k = f"{base}_{k}", k + 1
                A.add_asset(data, asset_id, "scene", f"{sc['title']} · image {pid_hint}", sc.get("summary", ""))
                A.save(data)
        with _slock:
            st = S.load()
            ch = _find_chapter(st, cid)
            sc = _find_scene(ch, sid)
            pid = _next_pid(sc)
            plan = {"id": pid, "from_line": from_line, "characters": [], "asset": asset_id}
            if src:
                plan["candidate"] = candidate
            sc["plans"].append(plan)
            sc["plans"].sort(key=lambda p: p["from_line"])
            S.save(st)
        self._json(200, {"ok": True, "plan": pid, "asset_id": asset_id})

    def _plan_update(self, cid: str, sid: str, pid: str, body: dict) -> None:
        with _slock:
            st = S.load()
            ch = _find_chapter(st, cid)
            sc = _find_scene(ch, sid)
            _guard(ch, sc, {"plans": None})
            plan = next((p for p in sc["plans"] if p["id"] == pid), None)
            if plan is None:
                raise KeyError(f"Image inconnue : {pid}")
            if body.get("delete"):
                sc["plans"].remove(plan)
            else:
                if "from_line" in body:
                    fl = int(body["from_line"])
                    if not 0 <= fl < len(sc.get("dialogue", [])):
                        raise ValueError("Le début d'image doit être une réplique existante")
                    plan["from_line"] = fl
                if "characters" in body:
                    chars = [str(c) for c in body["characters"]]
                    if not set(chars) <= set(sc.get("characters", [])):
                        raise ValueError("Personnages absents de la scène")
                    plan["characters"] = chars
                if "shot" in body:
                    shot = body["shot"] or {}
                    if shot.get("framing") and shot["framing"] not in SC.FRAMINGS:
                        raise ValueError(f"Cadrage inconnu : {shot['framing']}")
                    if shot.get("angle") and shot["angle"] not in SC.ANGLES:
                        raise ValueError(f"Angle inconnu : {shot['angle']}")
                    plan["shot"] = {"framing": shot.get("framing") or "", "angle": shot.get("angle") or "",
                                    "note": str(shot.get("note") or "").strip()}
                if "refs_exclude" in body:
                    plan["refs_exclude"] = [str(x) for x in body["refs_exclude"]]
                if "refs_extra" in body:
                    known = A.load()["assets"]
                    extra = []
                    for aid in body["refs_extra"]:
                        aid = str(aid)
                        if aid == plan["asset"]:
                            continue
                        if aid not in known:
                            raise ValueError(f"Image de référence inconnue : {aid}")
                        if aid not in extra:
                            extra.append(aid)
                    plan["refs_extra"] = extra
                sc["plans"].sort(key=lambda p: p["from_line"])
            S.save(st)
        self._json(200, {"ok": True})

    def _plan_suggest(self, cid: str, sid: str, pid: str, body: dict) -> None:
        with _slock:
            st = S.load()
        ch = _find_chapter(st, cid)
        sc = _find_scene(ch, sid)
        k = next((i for i, p in enumerate(sc["plans"]) if p["id"] == pid), None)
        if k is None:
            raise KeyError(f"Image inconnue : {pid}")
        data = A.load()
        text = SC.suggest(st, data, sc, k, body.get("provider") or None)
        self._json(200, {"prompt": text, "warnings": A.english_warnings(text),
                         "asset_id": sc["plans"][k]["asset"]})

    # ----- histoire -----
    def _story_settings(self, path: str, body: dict) -> None:
        with _slock:
            st = S.load()
            if path == "/api/story/meta":
                for k in ("title", "idea", "synopsis"):
                    if k in body:
                        st[k] = str(body[k])
            else:
                se = st["settings"]
                if "explicit_content" in body:
                    se["explicit_content"] = bool(body["explicit_content"])
                if "total_scenes" in body:
                    se["total_scenes"] = int(body["total_scenes"])
                for role, val in (body.get("providers") or {}).items():
                    if val not in S.PROVIDER_CHOICES.get(role, set()):
                        raise ValueError(f"{role} : '{val}' non reconnu")
                    se["providers"][role] = val
            S.save(st)
            self._json(200, _story_view())

    def _chapter_generate(self, body: dict) -> None:
        n = int(body.get("scene_count", 3))
        if not 1 <= n <= 12:
            raise ValueError("Taille de chapitre entre 1 et 12 scènes")
        guidance = str(body.get("guidance", "")).strip()
        provider = body.get("provider") or None
        if provider and provider not in S.PROVIDER_CHOICES["text"]:
            raise ValueError(f"fournisseur texte inconnu : {provider}")
        with _slock:
            snapshot = S.load()
        job_id = uuid.uuid4().hex[:12]
        _jobs[job_id] = {"state": "running", "message": "le modèle écrit le chapitre…", "candidate": None}

        def work():
            try:
                ch = P.generate_chapter(snapshot, n, guidance, provider)
                with _slock:
                    st = S.load()
                    P.add_generated(st, ch)
                    S.save(st)
                _jobs[job_id].update(state="done", message=f"{ch['id']} ajouté ({n} scènes)")
            except Exception as e:
                traceback.print_exc()
                _jobs[job_id].update(state="error", message=f"{type(e).__name__}: {e}")

        threading.Thread(target=work, daemon=True).start()
        self._json(202, {"job": job_id})

    def _dialogue_generate(self, cid: str, sid: str, body: dict) -> None:
        with _slock:
            st = S.load()
            ch = _find_chapter(st, cid)
            sc = _find_scene(ch, sid)
            _guard(ch, sc, {"dialogue": None})
        provider = body.get("provider") or None
        if provider and provider not in S.PROVIDER_CHOICES["text"]:
            raise ValueError(f"fournisseur texte inconnu : {provider}")
        job_id = uuid.uuid4().hex[:12]
        _jobs[job_id] = {"state": "running", "message": "le modèle écrit les répliques…", "candidate": None}

        def work():
            try:
                lines = P.generate_dialogue(st, sid, provider)
                with _slock:
                    st2 = S.load()
                    ch2 = _find_chapter(st2, cid)
                    sc2 = _find_scene(ch2, sid)
                    _guard(ch2, sc2, {"dialogue": None})
                    sc2["dialogue"] = lines
                    S.save(st2)
                _jobs[job_id].update(state="done", message=f"{len(lines)} répliques écrites pour {sid}")
            except Exception as e:
                traceback.print_exc()
                _jobs[job_id].update(state="error", message=f"{type(e).__name__}: {e}")

        threading.Thread(target=work, daemon=True).start()
        self._json(202, {"job": job_id})

    def _chapter_update(self, cid: str, body: dict) -> None:
        with _slock:
            st = S.load()
            ch = _find_chapter(st, cid)
            _guard(ch, None, body)
            for k in ("title", "summary"):
                if k in body:
                    ch[k] = str(body[k])
            if "locked" in body:
                ch["locked"] = bool(body["locked"])
            S.save(st)
            self._json(200, _story_view())

    def _chapter_delete(self, cid: str) -> None:
        with _slock:
            st = S.load()
            if not st["chapters"] or st["chapters"][-1]["id"] != cid:
                raise ValueError("Seul le dernier chapitre peut être supprimé (les numéros suivent l'ordre)")
            if st["chapters"][-1].get("locked"):
                raise ValueError("Chapitre verrouillé : déverrouillez-le pour le supprimer")
            st["chapters"].pop()
            S.save(st)
            self._json(200, _story_view())

    def _scene_update(self, cid: str, sid: str, body: dict) -> None:
        with _slock:
            st = S.load()
            ch = _find_chapter(st, cid)
            sc = _find_scene(ch, sid)
            _guard(ch, sc, body)
            for k in ("title", "summary", "location"):
                if k in body:
                    sc[k] = str(body[k]).strip() or None if k == "location" else str(body[k])
            if "characters" in body:
                sc["characters"] = [str(c).strip() for c in body["characters"] if str(c).strip()]
            if "outfits" in body:
                sc["outfits"] = {str(k2): str(v) for k2, v in body["outfits"].items()}
            if "ending" in body:
                sc["ending"] = bool(body["ending"])
            if "dialogue" in body:
                sc["dialogue"] = _clean_dialogue(body["dialogue"], sc)
            if "locked" in body:
                sc["locked"] = bool(body["locked"])
            S.save(st)
            self._json(200, _story_view())

    def _create_asset(self, body: dict) -> None:
        with _lock:
            data = A.load()
            A.add_asset(data, body["id"], body["kind"], body.get("name", ""), body.get("description", ""), body.get("parent"))
            data["assets"][body["id"]]["prompt"] = body.get("prompt", "")
            A.save(data)
        self._json(200, {"ok": True})

    def _update_asset(self, aid: str, body: dict) -> None:
        with _lock:
            data = A.load()
            a = data["assets"].get(aid)
            if a is None:
                raise KeyError(f"Actif inconnu : {aid}")
            for key in ("name", "description", "prompt", "parent"):
                if key in body:
                    a[key] = body[key] or None if key == "parent" else body[key]
            A.save(data)
        self._json(200, {"ok": True})

    def _set_status(self, aid: str, index: int, body: dict) -> None:
        with _lock:
            data = A.load()
            A.set_status(data, aid, index, bool(body.get("validate")))
            A.save(data)
        self._json(200, {"ok": True})

    def _generate(self, body: dict) -> None:
        aid = body["id"]
        prompt = (body.get("prompt") or "").strip()
        if not prompt:
            raise ValueError("Prompt vide")
        job_id = uuid.uuid4().hex[:12]
        _jobs[job_id] = {"state": "running", "message": "génération en cours…", "candidate": None}

        def work():
            try:
                _load_token_from_keyfile()
                with _lock:
                    data = A.load()
                    idx = A.generate(data, aid, body.get("refs", []), prompt,
                                     body.get("seed"), "replicate", body.get("aspect") or None)
                    A.save(data)
                _jobs[job_id].update(state="done", message="candidat créé", candidate=idx)
            except Exception as e:
                traceback.print_exc()
                _jobs[job_id].update(state="error", message=f"{type(e).__name__}: {e}")

        threading.Thread(target=work, daemon=True).start()
        self._json(202, {"job": job_id})


def _story_view() -> dict:
    st = S.load()
    return {"story": st, "errors": S.validate(st, A.load()), "providers": {k: sorted(v) for k, v in S.PROVIDER_CHOICES.items()}}


def _find_chapter(st: dict, cid: str) -> dict:
    for ch in st["chapters"]:
        if ch["id"] == cid:
            return ch
    raise KeyError(f"Chapitre inconnu : {cid}")


def _guard(ch: dict, sc: dict | None, body: dict) -> None:
    """Refuse une modification sur un élément verrouillé. Changer seulement le verrou reste permis."""
    if set(body) <= {"locked"}:
        return
    if S.is_locked(ch, sc):
        raise ValueError("Verrouillé : déverrouillez-le avant de le modifier")


def _next_pid(sc: dict) -> str:
    """Premier identifiant d'image libre dans la scène (p1, p2…), même après une suppression."""
    used = {int(p["id"][1:]) for p in sc.get("plans", []) if re.fullmatch(r"p\d+", p["id"])}
    n = 1
    while n in used:
        n += 1
    return f"p{n}"


def _slug(text: str) -> str:
    import unicodedata
    ascii_ = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "_", ascii_).strip("_")[:40] or "element"


def _clean_dialogue(lines, sc: dict) -> list[dict]:
    """Valide des répliques saisies à la main."""
    if not isinstance(lines, list):
        raise ValueError("dialogue : liste attendue")
    allowed = set(sc.get("characters", [])) | {S.NARRATOR}
    out = []
    for i, line in enumerate(lines, 1):
        speaker = str(line.get("speaker", "")).strip()
        text = str(line.get("text", "")).strip()
        if speaker not in allowed:
            raise ValueError(f"Réplique {i} : locuteur « {speaker} » absent de la scène")
        if not text:
            raise ValueError(f"Réplique {i} vide")
        out.append({"speaker": speaker, "text": text,
                    "expression": str(line.get("expression") or "neutre").strip()})
    return out


def _find_scene(ch: dict, sid: str) -> dict:
    for sc in ch["scenes"]:
        if sc["id"] == sid:
            return sc
    raise KeyError(f"Scène inconnue : {sid}")



def main() -> None:
    _load_token_from_keyfile()
    srv = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"Registre d'actifs : http://{HOST}:{PORT}", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
