"""Registre d'actifs : personnages, tenues, lieux.

Source de vérité : game_spec/assets.yaml. Chaque actif a une liste de candidats (images
générées, avec leur métadonnée complète) et au plus un candidat validé par un humain.
Le graphe d'histoire ne doit référencer que des actifs validés (require_validated).

Usage :
    python assets.py list
    python assets.py add <id> <kind> "<nom>" "<description>"
    python assets.py generate <id> [--refs id1,id2] [--prompt "texte exact"] [--seed N] [--aspect 16:9]
    python assets.py validate <id> <numéro_candidat>
    python assets.py reject <id> <numéro_candidat>
    python assets.py check
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent
SPEC = ROOT / "game_spec" / "assets.yaml"
CONFIG = ROOT / "config.yaml"
KINDS = {"character", "outfit", "location", "scene", "object"}
DEFAULT_ASPECT = {"character": "2:3", "outfit": "2:3", "location": "16:9", "scene": "16:9", "object": "1:1"}


# ---------- lecture / écriture ----------

def load(path: Path = SPEC) -> dict:
    if not path.exists():
        return {"version": 1, "assets": {}}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {"version": 1, "assets": {}}


def save(data: dict, path: Path = SPEC) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")


def _get(data: dict, asset_id: str) -> dict:
    try:
        return data["assets"][asset_id]
    except KeyError:
        raise KeyError(f"Actif inconnu : {asset_id}") from None


# ---------- règle de validation ----------

def validated_path(asset_id: str, data: dict | None = None) -> Path:
    """Chemin de l'image validée. Lève une erreur si l'actif ne l'est pas."""
    data = data if data is not None else load()
    a = _get(data, asset_id)
    if a.get("status") != "validated" or a.get("validated_candidate") is None:
        raise ValueError(f"Actif non validé : {asset_id} (statut {a.get('status')})")
    cand = a["candidates"][a["validated_candidate"]]
    return ROOT / cand["file"]


def check(data: dict | None = None) -> list[str]:
    """Renvoie les problèmes du registre (fichiers manquants, actifs non validés)."""
    data = data if data is not None else load()
    problems = []
    for aid, a in data.get("assets", {}).items():
        if a.get("kind") not in KINDS:
            problems.append(f"{aid}: kind invalide ({a.get('kind')})")
        for i, c in enumerate(a.get("candidates", [])):
            if not (ROOT / c["file"]).exists():
                problems.append(f"{aid}[{i}]: fichier absent {c['file']}")
        if a.get("status") == "validated" and a.get("validated_candidate") is None:
            problems.append(f"{aid}: statut validé sans candidat choisi")
    return problems


# ---------- opérations ----------

def add_asset(data: dict, asset_id: str, kind: str, name: str, description: str,
              parent: str | None = None) -> None:
    if kind not in KINDS:
        raise ValueError(f"kind doit être dans {sorted(KINDS)}")
    if asset_id in data["assets"]:
        raise ValueError(f"Actif déjà existant : {asset_id}")
    data["assets"][asset_id] = {
        "kind": kind,
        "name": name,
        "description": description,
        "parent": parent,              # ex. une tenue appartient à un personnage
        "status": "draft",             # draft | validated | rejected
        "validated_candidate": None,
        "candidates": [],
    }


def add_candidate(data: dict, asset_id: str, file: str, meta: dict) -> int:
    a = _get(data, asset_id)
    a["candidates"].append({"file": file, "created": dt.datetime.now().isoformat(timespec="seconds"), **meta})
    return len(a["candidates"]) - 1


def set_status(data: dict, asset_id: str, index: int, validate: bool) -> None:
    a = _get(data, asset_id)
    if not 0 <= index < len(a["candidates"]):
        raise IndexError(f"{asset_id} n'a pas de candidat {index}")
    if validate:
        a["status"] = "validated"
        a["validated_candidate"] = index
    else:
        if a.get("validated_candidate") == index:
            a["status"] = "draft"
            a["validated_candidate"] = None
        a["candidates"][index]["rejected"] = True


# ---------- génération ----------

def reference_style() -> dict:
    """Style de référence défini dans config.yaml. Il n'est jamais ajouté automatiquement."""
    cfg = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    return cfg["visual_style"]


FRENCH_CHARS = set("éèêëàâçùûôîïœÉÈÀÇ")
FRENCH_WORDS = {"le", "la", "les", "une", "un", "de", "des", "du", "et", "avec", "dans",
                "femme", "homme", "cheveux", "yeux", "robe", "cuisine", "sur", "qui", "pour"}


def english_warnings(text: str) -> list[str]:
    """Avertissements (non bloquants) : mots ou accents français dans un prompt."""
    words = {w.strip(".,;:!?()").lower() for w in text.split()}
    if FRENCH_CHARS & set(text) or words & FRENCH_WORDS:
        return ["Le texte contient du français : les modèles Flux répondent mieux en anglais."]
    return []


def split_ref(ref: str) -> tuple[str, int | None]:
    """« aid » = image retenue de l'élément ; « aid@k » = candidat k précis, retenu ou non."""
    if "@" in ref:
        aid, k = ref.rsplit("@", 1)
        return aid, int(k)
    return ref, None


def ref_path(ref: str, data: dict) -> Path:
    aid, k = split_ref(ref)
    if k is None:
        return validated_path(aid, data)
    a = _get(data, aid)
    if not 0 <= k < len(a["candidates"]):
        raise ValueError(f"Candidat {k} inconnu pour {aid}")
    return ROOT / a["candidates"][k]["file"]


def generate(data: dict, asset_id: str, ref_ids: list[str], prompt: str, seed: int | None,
             backend: str = "replicate", aspect: str | None = None) -> int:
    """Génère un candidat. `prompt` est envoyé tel quel, sans ajout ni modification."""
    a = _get(data, asset_id)
    if not prompt or not prompt.strip():
        raise ValueError("Prompt vide")
    refs = [ref_path(r, data) for r in ref_ids]
    n = len(a["candidates"])
    out_rel = f"assets/{asset_id}/cand_{n:02d}.png"
    out_abs = ROOT / out_rel

    if backend != "replicate":
        raise NotImplementedError(f"Backend '{backend}' pas encore branché (ComfyUI : phase P4)")
    import image_replicate as rep

    aspect = aspect or DEFAULT_ASPECT[a["kind"]]
    model = rep.generate(prompt, out_abs, images=refs or None, seed=seed, aspect_ratio=aspect)

    return add_candidate(data, asset_id, out_rel, {
        "backend": backend,
        "model": model,
        "seed": seed,
        "prompt": prompt,
        "refs": ref_ids,
        "aspect": aspect,
    })


# ---------- CLI ----------

def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    sub.add_parser("check")
    p = sub.add_parser("add"); p.add_argument("id"); p.add_argument("kind"); p.add_argument("name"); p.add_argument("description"); p.add_argument("--parent")
    p = sub.add_parser("generate"); p.add_argument("id"); p.add_argument("--refs", default=""); p.add_argument("--prompt", help="prompt exact (par défaut : prompt de l'actif)"); p.add_argument("--seed", type=int); p.add_argument("--aspect"); p.add_argument("--backend", default="replicate")
    p = sub.add_parser("validate"); p.add_argument("id"); p.add_argument("index", type=int)
    p = sub.add_parser("reject"); p.add_argument("id"); p.add_argument("index", type=int)
    args = ap.parse_args()

    data = load()
    if args.cmd == "list":
        for aid, a in data["assets"].items():
            print(f"{aid:24} {a['kind']:10} {a['status']:10} candidats={len(a['candidates'])} validé={a['validated_candidate']}")
    elif args.cmd == "check":
        probs = check(data)
        print("\n".join(probs) if probs else "OK")
        sys.exit(1 if probs else 0)
    elif args.cmd == "add":
        add_asset(data, args.id, args.kind, args.name, args.description, args.parent)
        save(data)
    elif args.cmd == "generate":
        refs = [r for r in args.refs.split(",") if r]
        prompt = args.prompt if args.prompt is not None else data["assets"][args.id].get("prompt", "")
        idx = generate(data, args.id, refs, prompt, args.seed, args.backend, args.aspect)
        save(data)
        print(f"candidat {idx} : {data['assets'][args.id]['candidates'][idx]['file']}")
    elif args.cmd == "validate":
        set_status(data, args.id, args.index, True); save(data)
    elif args.cmd == "reject":
        set_status(data, args.id, args.index, False); save(data)


if __name__ == "__main__":
    main()
