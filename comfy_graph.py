"""Lecture et modification d'un workflow ComfyUI (format API : {id: {class_type, inputs}}).

Un workflow est un graphe. Un lien est écrit [id_du_nœud, numéro_de_sortie] dans les entrées.
Ce module ne fait pas de réseau : il lit, décrit, retrouve les rôles (prompt, taille, graine, modèle,
sortie…) par le TYPE des nœuds — jamais par leur numéro — et insère des LoRA dans le graphe.

Usage en ligne de commande :
    python3 comfy_graph.py workflow.json                  # décrit le graphe et ses rôles
    python3 comfy_graph.py workflow.json --lora nom.safetensors:0.8 --out nouveau.json
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

LOADERS_MODEL = {"UNETLoader", "CheckpointLoaderSimple", "UnetLoaderGGUF"}
LOADERS_CLIP = {"DualCLIPLoader", "CLIPLoader"}
LATENT_SIZE = {"EmptyLatentImage", "EmptySD3LatentImage", "EmptyHunyuanLatentVideo"}
LORA_MODEL_ONLY = "LoraLoaderModelOnly"   # LoRA qui modifie seulement le modèle (cas le plus courant en FLUX)
LORA_MODEL_CLIP = "LoraLoader"            # LoRA qui modifie aussi l'encodeur de texte


def load(path: Path | str) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def is_link(value) -> bool:
    return isinstance(value, list) and len(value) == 2 and isinstance(value[0], str) and isinstance(value[1], int)


def links_from(graph: dict, node_id: str) -> list[tuple[str, str, int]]:
    """Qui consomme la sortie de node_id : [(id_consommateur, nom_entrée, numéro_de_sortie)]."""
    out = []
    for nid, node in graph.items():
        for name, value in node.get("inputs", {}).items():
            if is_link(value) and value[0] == node_id:
                out.append((nid, name, value[1]))
    return out


def _reaches_input(graph: dict, start: str, wanted: set[str]) -> str | None:
    """Parcourt le graphe vers l'aval depuis start et renvoie le nom de la première entrée rencontrée
    parmi `wanted` (ex. « positive » ou « negative »)."""
    seen, stack = set(), [start]
    while stack:
        current = stack.pop()
        if current in seen:
            continue
        seen.add(current)
        for consumer, name, _ in links_from(graph, current):
            if name in wanted:
                return name
            stack.append(consumer)
    return None


def roles(graph: dict) -> dict:
    """Rôles des nœuds, par type. Une liste vide signifie « non trouvé »."""
    r = {"positive_prompt": [], "negative_prompt": [], "model": [], "clip": [], "latent_size": [],
         "seed": [], "steps": [], "reference_images": [], "outputs": []}
    for nid in sorted(graph, key=_sort_key):
        node = graph[nid]
        cls, inputs = node.get("class_type", ""), node.get("inputs", {})
        if cls == "CLIPTextEncode":
            side = _reaches_input(graph, nid, {"positive", "negative"})
            if side == "positive":
                r["positive_prompt"].append(nid)
            elif side == "negative":
                r["negative_prompt"].append(nid)
            else:
                r["positive_prompt"].append(nid)  # pas de guidage négatif relié : c'est le prompt principal
        elif cls in LOADERS_MODEL:
            r["model"].append(nid)
        elif cls in LOADERS_CLIP:
            r["clip"].append(nid)
        elif cls in LATENT_SIZE or ("width" in inputs and "height" in inputs and cls != "LoadImage"):
            r["latent_size"].append(nid)
        if "noise_seed" in inputs or ("seed" in inputs and not is_link(inputs["seed"])):
            r["seed"].append(nid)
        if "steps" in inputs and not is_link(inputs["steps"]):
            r["steps"].append(nid)
        if cls == "LoadImage":
            r["reference_images"].append(nid)
        if cls == "SaveImage":
            r["outputs"].append(nid)
    return r


def _sort_key(nid: str):
    return (0, int(nid)) if nid.isdigit() else (1, nid)


def describe(graph: dict) -> str:
    """Texte lisible : les rôles, puis chaque nœud avec ses réglages et ses liens."""
    lines = ["Rôles détectés :"]
    for role, ids in roles(graph).items():
        lines.append(f"  {role:<18} {', '.join(ids) if ids else '—'}")
    lines.append("")
    lines.append("Nœuds :")
    for nid in sorted(graph, key=_sort_key):
        node = graph[nid]
        settings, links = [], []
        for name, value in node.get("inputs", {}).items():
            if is_link(value):
                links.append(f"{name}←{value[0]}")
            else:
                text = str(value)
                settings.append(f"{name}={text[:50] + '…' if len(text) > 50 else text}")
        lines.append(f"  [{nid}] {node.get('class_type', '?')}  " + ", ".join(settings + links))
    return "\n".join(lines)


def check(graph: dict) -> list[str]:
    """Problèmes évidents : liens vers des nœuds absents, types manquants."""
    problems = []
    for nid, node in graph.items():
        if "class_type" not in node:
            problems.append(f"nœud {nid} sans type")
        for name, value in node.get("inputs", {}).items():
            if is_link(value) and value[0] not in graph:
                problems.append(f"nœud {nid} ({name}) pointe vers le nœud absent {value[0]}")
    return problems


def _next_id(graph: dict) -> str:
    numbers = [int(k) for k in graph if k.isdigit()]
    return str((max(numbers) if numbers else 0) + 1)


def insert_loras(graph: dict, loras: list[tuple[str, float]], model_loader: str | None = None,
                 clip_loader: str | None = None, with_clip: bool = False) -> dict:
    """Renvoie une copie du graphe où les LoRA sont insérés juste après le chargeur de modèle.

    Chaque consommateur du modèle (échantillonneur, planificateur, guidage…) est rebranché sur la
    dernière LoRA de la chaîne. Avec with_clip=True, les LoRA modifient aussi l'encodeur de texte.
    """
    result = copy.deepcopy(graph)
    rl = roles(graph)
    model_loader = model_loader or (rl["model"][0] if rl["model"] else None)
    if model_loader is None:
        raise ValueError("Aucun chargeur de modèle trouvé dans le workflow")
    clip_loader = clip_loader or (rl["clip"][0] if rl["clip"] else None)
    if with_clip and clip_loader is None:
        raise ValueError("LoRA avec texte demandée, mais aucun chargeur CLIP trouvé")

    model_src, clip_src = [model_loader, 0], ([clip_loader, 0] if clip_loader else None)
    original_consumers = links_from(graph, model_loader)
    clip_consumers = links_from(graph, clip_loader) if (with_clip and clip_loader) else []
    for name, strength in loras:
        nid = _next_id(result)
        if with_clip:
            result[nid] = {"class_type": LORA_MODEL_CLIP, "inputs": {
                "model": model_src, "clip": clip_src, "lora_name": name,
                "strength_model": float(strength), "strength_clip": float(strength)}}
            clip_src = [nid, 1]
        else:
            result[nid] = {"class_type": LORA_MODEL_ONLY, "inputs": {
                "model": model_src, "lora_name": name, "strength_model": float(strength)}}
        model_src = [nid, 0]

    new_ids = set(result) - set(graph)
    for consumer, name, _ in original_consumers:
        if consumer not in new_ids and name == "model":
            result[consumer]["inputs"]["model"] = model_src
    if with_clip:
        for consumer, name, _ in clip_consumers:
            if consumer not in new_ids and name == "clip":
                result[consumer]["inputs"]["clip"] = clip_src
    return result


def _upstream(graph: dict, nid: str, seen: set | None = None) -> set:
    """Nœuds dont dépend nid (nid compris)."""
    seen = set() if seen is None else seen
    if nid in seen or nid not in graph:
        return seen
    seen.add(nid)
    for value in graph[nid].get("inputs", {}).values():
        if is_link(value):
            _upstream(graph, value[0], seen)
    return seen


def prune_unused_references(graph: dict, keep: int) -> dict:
    """Retire les emplacements d'image de référence au-delà de « keep » (ordre des LoadImage).

    Pour chaque emplacement retiré : son chargement d'image, sa mise à l'échelle, son encodage et son
    ReferenceLatent disparaissent, et ce qui les consommait est rebranché sur la chaîne qui précède.
    Une copie est renvoyée ; le graphe d'origine n'est pas modifié.
    """
    result = copy.deepcopy(graph)
    slots = roles(result)["reference_images"]
    unused = set(slots[keep:])
    if not unused:
        return result

    def latent_depends_on_unused(ref_id: str) -> bool:
        latent = result[ref_id].get("inputs", {}).get("latent")
        return is_link(latent) and bool(_upstream(result, latent[0]) & unused)

    doomed = {nid for nid, n in result.items()
              if n.get("class_type") == "ReferenceLatent" and latent_depends_on_unused(nid)}
    # Les nœuds qui consommaient un ReferenceLatent retiré reprennent son conditionnement d'entrée.
    for ref_id in doomed:
        source = result[ref_id]["inputs"]["conditioning"]
        for node in result.values():
            for name, value in node.get("inputs", {}).items():
                if is_link(value) and value[0] == ref_id:
                    node["inputs"][name] = source
    for ref_id in doomed:
        del result[ref_id]

    # Nœuds de traitement des emplacements retirés, tant qu'ils ne servent plus à rien.
    candidates = set()
    for ref_id in doomed:
        latent = graph[ref_id].get("inputs", {}).get("latent")
        if is_link(latent):
            candidates |= _upstream(graph, latent[0])  # encodage, mise à l'échelle, chargement de l'image
    changed = True
    while changed:
        changed = False
        for nid in sorted(candidates & set(result)):
            consumed = any(is_link(v) and v[0] == nid
                           for node in result.values() for v in node.get("inputs", {}).values())
            if not consumed:
                del result[nid]
                changed = True
    return result


def main(argv: list[str]) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="Décrit un workflow ComfyUI et insère des LoRA.")
    ap.add_argument("workflow", type=Path)
    ap.add_argument("--lora", action="append", default=[], help="nom.safetensors:force (répétable)")
    ap.add_argument("--with-clip", action="store_true", help="les LoRA modifient aussi le texte")
    ap.add_argument("--out", type=Path, help="écrit le graphe modifié dans ce fichier")
    args = ap.parse_args(argv)
    graph = load(args.workflow)
    print(describe(graph))
    problems = check(graph)
    if problems:
        print("\nProblèmes :\n  " + "\n  ".join(problems))
    if args.lora:
        pairs = []
        for item in args.lora:
            name, _, strength = item.partition(":")
            pairs.append((name, float(strength or 1.0)))
        graph = insert_loras(graph, pairs, with_clip=args.with_clip)
        print(f"\nAprès insertion de {len(pairs)} LoRA :")
        print(describe(graph))
        if args.out:
            args.out.write_text(json.dumps(graph, indent=2, ensure_ascii=False), encoding="utf-8")
            print(f"\nÉcrit : {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
