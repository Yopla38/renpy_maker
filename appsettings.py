"""Réglages choisis dans l'application (roue de réglages) : game_spec/app_settings.yaml.

Les valeurs par défaut sont dans config.yaml (llm_tasks, image_engines). Un choix fait dans l'application
les remplace, sans toucher au fichier de configuration (qui garde ses commentaires).

Tâches d'écriture : histoire (plan des chapitres), dialogue (répliques), prompt (prompts d'image et découpage).
Rôles d'image    : base (sans référence, « équivalent FLUX 1 »), edit (avec références, « équivalent Klein »).
"""

from __future__ import annotations

import json
from pathlib import Path

import yaml

import paths

TASKS = ("histoire", "dialogue", "prompt", "decision")
ROLES = ("base", "edit")
ENGINES = ("replicate", "comfyui")


def config() -> dict:
    return yaml.safe_load((paths.CODE / "config.yaml").read_text(encoding="utf-8")) or {}


def load() -> dict:
    if not paths.app_settings_file().exists():
        return {}
    return yaml.safe_load(paths.app_settings_file().read_text(encoding="utf-8")) or {}


def save(data: dict) -> None:
    FILE = paths.app_settings_file()
    FILE.parent.mkdir(parents=True, exist_ok=True)
    FILE.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")


def llm_for(task: str, story_provider: str) -> tuple[str, str]:
    """(fournisseur, modèle) pour une tâche d'écriture. Le modèle vide = modèle par défaut du fournisseur."""
    if task not in TASKS:
        raise ValueError(f"Tâche inconnue : {task}")
    chosen = (load().get("llm_tasks") or {}).get(task) or {}
    default = (config().get("llm_tasks") or {}).get(task) or {}
    if chosen.get("provider"):
        return chosen["provider"], chosen.get("model") or ""
    if default.get("provider"):
        return default["provider"], default.get("model") or ""
    return story_provider, ""


def image_for(role: str) -> dict:
    """Moteur et workflow d'un rôle d'image. L'application enfants reste sur Replicate."""
    if role not in ROLES:
        raise ValueError(f"Rôle inconnu : {role}")
    default = (config().get("image_engines") or {}).get(role) or {}
    chosen = (load().get("image_engines") or {}).get(role) or {}
    engine = chosen.get("engine") or default.get("engine") or "replicate"
    workflow = chosen.get("workflow") or default.get("workflow") or None
    if paths.KIDS:
        engine = "replicate"
    if engine == "comfyui" and not workflow:
        workflow = (config().get("comfy_workflows") or {}).get(role)  # workflow proposé par défaut
    if workflow and not Path(workflow).is_absolute():
        workflow = str(paths.CODE / workflow)
    return {"engine": engine, "workflow": workflow}


WORKFLOW_DIR = paths.CODE / "comfy" / "workflows"


def available_workflows() -> list[str]:
    """Workflows ComfyUI proposés dans la roue : fichiers au format API du dossier comfy/workflows."""
    found = []
    for path in sorted(WORKFLOW_DIR.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(data, dict) and data and all(isinstance(v, dict) and "class_type" in v for v in data.values()):
            found.append(path.relative_to(paths.CODE).as_posix())
    return found


def default_comfy_workflow(role: str) -> str:
    """Workflow ComfyUI proposé par défaut pour un rôle, chemin complet."""
    rel = (config().get("comfy_workflows") or {}).get(role)
    if not rel:
        raise ValueError(f"Aucun workflow ComfyUI par défaut pour le rôle {role}")
    return str(paths.CODE / rel) if not Path(rel).is_absolute() else rel


def steps_for(role: str) -> int | None:
    """Nombre d'étapes voulu pour un rôle, ou None pour garder celui du workflow."""
    chosen = (load().get("comfy_steps") or {}).get(role)
    value = chosen if chosen is not None else (config().get("comfy_steps") or {}).get(role)
    if value is None:
        return None
    value = int(value)
    if not 1 <= value <= 100:
        raise ValueError("Le nombre d'étapes doit être entre 1 et 100")
    return value


def _comfy_flag(key: str, default: bool) -> bool:
    chosen = load().get(key)
    if chosen is not None:
        return bool(chosen)
    return bool((config().get("comfy") or {}).get(key, default))


def unload_ollama_before_comfy() -> bool:
    """Décharger les modèles Ollama avant une génération ComfyUI."""
    return _comfy_flag("unload_ollama_before_comfy", True)


def free_comfy_before_ollama() -> bool:
    """Libérer la mémoire ComfyUI avant un appel Ollama."""
    return _comfy_flag("free_comfy_before_ollama", False)


def comfy_free_memory() -> bool:
    """Libérer la mémoire de ComfyUI avant chaque génération (réglage de la machine)."""
    chosen = load().get("comfy_free_memory")
    if chosen is not None:
        return bool(chosen)
    return bool((config().get("comfy") or {}).get("free_memory_before_generation", False))
