"""Génération d'image par ComfyUI, avec le workflow choisi dans la roue de réglages.

Le graphe est lu par TYPE de nœud (comfy_graph) : le prompt, la taille, la graine, les images de référence
et la sortie sont trouvés sans numéro fixe. Les LoRA demandés sont insérés dans le graphe avant envoi.
"""

from __future__ import annotations

import random
import shutil
import uuid
from pathlib import Path

import appsettings
import comfy_client as CC
import comfy_graph as CG

ASPECTS = {"2:3": (832, 1216), "3:2": (1216, 832), "16:9": (1344, 768), "9:16": (768, 1344), "1:1": (1024, 1024)}


def base_url() -> str:
    return appsettings.config().get("comfy", {}).get("url", CC.DEFAULT_URL)


def _upload_reference(path: Path, index: int, base: str, scratch: Path) -> str:
    """Envoie une image de référence sous un nom unique. Sans cela, toutes les références s'appellent
    « cand_00.png » : ComfyUI n'en garde qu'une, et chaque emplacement reçoit la même image."""
    unique = scratch / f"ref{index}_{uuid.uuid4().hex[:8]}_{path.parent.name}.png"
    shutil.copyfile(path, unique)
    try:
        return CC.upload_image(unique, base)
    finally:
        unique.unlink(missing_ok=True)


def free_memory(base: str) -> None:
    """Demande à ComfyUI de décharger les modèles et de vider la mémoire GPU. Sans effet bloquant."""
    import json
    import urllib.request
    req = urllib.request.Request(base + "/free", data=json.dumps({"unload_models": True, "free_memory": True}).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=60):
            pass
    except OSError:
        pass  # ComfyUI injoignable : la génération échouera avec son propre message


def generate(workflow: str | None, prompt: str, refs: list[Path], loras: list[dict], aspect: str | None,
             out_path: Path, seed: int | None = None, timeout_s: int = 1800, steps: int | None = None,
             on_progress=None, on_submit=None) -> str:
    """Écrit l'image dans out_path et renvoie le nom du workflow utilisé (pour le manifeste)."""
    if not workflow:
        raise ValueError("Aucun workflow ComfyUI choisi pour ce rôle : choisissez-le dans la roue de réglages")
    base = base_url()
    if appsettings.unload_ollama_before_comfy():
        import llm
        llm.unload_ollama_models()  # un modèle Ollama chargé occuperait la VRAM dont ComfyUI a besoin
    if appsettings.comfy_free_memory():
        free_memory(base)
    graph = CC.load_workflow(Path(workflow), base)
    problems = CG.check(graph)
    if problems:
        raise ValueError("Workflow ComfyUI incohérent : " + " ; ".join(problems[:3]))
    rl = CG.roles(graph)
    if not rl["positive_prompt"]:
        raise ValueError("Le workflow n'a pas de prompt positif reconnu (un nœud d'encodage de texte relié au guidage)")

    graph[rl["positive_prompt"][0]]["inputs"]["text"] = prompt
    width, height = ASPECTS.get(aspect or "2:3", ASPECTS["2:3"])
    for nid in rl["latent_size"]:
        graph[nid]["inputs"]["width"], graph[nid]["inputs"]["height"] = width, height
    if steps is not None:
        for nid in rl["steps"]:
            graph[nid]["inputs"]["steps"] = int(steps)
    value = seed if seed is not None else random.randint(1, 2**31 - 1)
    for nid in rl["seed"]:
        key = "noise_seed" if "noise_seed" in graph[nid]["inputs"] else "seed"
        graph[nid]["inputs"][key] = value

    slot_count = len(rl["reference_images"])
    if len(refs) > slot_count:
        raise ValueError(f"Ce workflow accepte {slot_count} image(s) de référence, {len(refs)} sont demandées")
    if slot_count:
        # Les emplacements non utilisés sont retirés : une image placeholder influencerait le résultat.
        graph = CG.prune_unused_references(graph, len(refs))
    slots = CG.roles(graph)["reference_images"]
    out_path.parent.mkdir(parents=True, exist_ok=True)
    for index, (nid, path) in enumerate(zip(slots, refs)):
        graph[nid]["inputs"]["image"] = _upload_reference(Path(path), index, base, out_path.parent)

    if loras:
        pairs = [(item["name"], float(item.get("strength", 1.0))) for item in loras]
        graph = CG.insert_loras(graph, pairs, with_clip=any(item.get("clip") for item in loras))

    files = CC.run(graph, base, timeout_s, on_progress=on_progress, on_submit=on_submit)
    if not files:
        raise RuntimeError("ComfyUI n'a produit aucune image")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    saved = CC.download(files[:1], out_path.parent, base)[0]
    saved.replace(out_path)
    return f"comfyui:{Path(workflow).name}"
