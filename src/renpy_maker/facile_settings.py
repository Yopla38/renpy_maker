"""Réglages du parcours simple : fournisseurs, moteurs, modèles, clés."""

from __future__ import annotations

from pathlib import Path

import yaml

from renpy_maker import appsettings
from renpy_maker import keys
from renpy_maker import llm
from renpy_maker import paths
from renpy_maker import story as S
from renpy_maker.facile_base import PLAN_LIMITS, available_loras

TEXT_LABELS = {"replicate": "Replicate (Llama)", "anthropic": "Anthropic (Claude)", "openai": "OpenAI",
               "ollama": "Ollama (local)"}

KIDS_TEXT = ("replicate",)   # application grand public : seul Replicate, même compte que les images

SECRET_NAMES = ("REPLICATE_API_TOKEN",)

def settings_view() -> dict:
    with S.LOCK:
        st = S.load()
    choices = []
    for name, label in TEXT_LABELS.items():
        if paths.KIDS and name not in KIDS_TEXT:
            continue
        cfg = llm.provider_settings(name)
        choices.append({"name": name, "label": label, "model": cfg.get("model", ""),
                        "key": llm.key_available(name)})
    return {
        "kids": paths.KIDS,
        "replicate_key": keys.present("REPLICATE_API_TOKEN"),
        "text": {"provider": appsettings.provider("text"), "choices": choices},
        "tasks": _tasks_view(st),
        "image_rows": _images_view(),
        "comfy_free_memory": appsettings.comfy_free_memory(),
        "unload_ollama_before_comfy": appsettings.unload_ollama_before_comfy(),
        "free_comfy_before_ollama": appsettings.free_comfy_before_ollama(),
        "comfy_defaults": {role: appsettings.default_comfy_workflow(role) for role in appsettings.ROLES},
        "engine_labels": ENGINE_LABELS,
        "loras": available_loras(),
        "image": {"provider": appsettings.provider("image_base"),
                  "choices": [{"name": "replicate", "label": "Replicate (cloud)", "available": True},
                              {"name": "comfyui", "label": "ComfyUI (local), bientôt", "available": False}],
                  "models": ["FLUX dev pour les ancres", "FLUX.2 Klein pour les retouches et les scènes"]},
        "explicit": bool(st["settings"].get("explicit_content")),
    }

def save_secret(name: str, value: str) -> dict:
    """Enregistre une clé saisie dans l'application, sur l'appareil seulement."""
    if name not in SECRET_NAMES:
        raise ValueError("Clé inconnue")
    if not value.strip():
        raise ValueError("La clé est vide")
    keys.set(name, value)
    return settings_view()

TASK_LABELS = {"histoire": "Histoire (plan des chapitres)", "dialogue": "Dialogue (répliques)",
               "prompt": "Prompts d'image et découpage", "decision": "Décisions (changement de tenue)"}

ENGINE_LABELS = {"replicate": "Replicate (cloud)", "comfyui": "ComfyUI (local)"}

def _tasks_view(st: dict) -> list[dict]:
    rows = []
    default_provider = appsettings.provider("text")
    for task, label in TASK_LABELS.items():
        provider, model = appsettings.llm_for(task, default_provider)
        rows.append({"task": task, "label": label, "provider": provider, "model": model})
    return rows

def _images_view() -> list[dict]:
    rows = []
    for role, label in (("base", "Dessin de base (sans référence)"), ("edit", "Retouche (avec références)")):
        choice = appsettings.image_for(role)
        workflow = choice["workflow"] or ""
        if workflow.startswith(str(paths.CODE) + "/"):
            workflow = workflow[len(str(paths.CODE)) + 1:]  # chemin relatif, comme dans la liste
        rows.append({"role": role, "label": label, "engine": choice["engine"], "workflow": workflow,
                     "steps": appsettings.steps_for(role) or "", "choices": appsettings.available_workflows()})
    return rows

def save_settings_tasks(body: dict) -> None:
    """Enregistre les choix par tâche et par moteur d'image (game_spec/app_settings.yaml)."""
    with appsettings.LOCK:
        _save_settings_tasks(body)


def _save_settings_tasks(body: dict) -> None:
    data = appsettings.load()
    tasks = body.get("tasks")
    if tasks is not None:
        chosen = {}
        for row in tasks:
            task = row.get("task")
            if task not in appsettings.TASKS:
                raise ValueError("Tâche inconnue")
            provider = row.get("provider") or ""
            if provider and provider not in TEXT_LABELS:
                raise ValueError("Fournisseur d'écriture inconnu")
            if provider and paths.KIDS and provider not in KIDS_TEXT:
                raise ValueError("Fournisseur non disponible dans cette application")
            chosen[task] = {"provider": provider or None, "model": str(row.get("model") or "").strip() or None}
        data["llm_tasks"] = chosen
    engines = body.get("images")
    if engines is not None:
        chosen = {}
        for row in engines:
            role = row.get("role")
            if role not in appsettings.ROLES:
                raise ValueError("Rôle d'image inconnu")
            engine = row.get("engine") or "replicate"
            if engine not in appsettings.ENGINES:
                raise ValueError("Moteur d'image inconnu")
            if paths.KIDS and engine != "replicate":
                raise ValueError("Cette application utilise Replicate pour les images")
            workflow = str(row.get("workflow") or "").strip() or None
            if engine == "comfyui":
                if not workflow:
                    workflow = appsettings.default_comfy_workflow(role)
                wf = Path(workflow) if Path(workflow).is_absolute() else paths.CODE / workflow
                if not appsettings.is_workflow(wf):
                    raise ValueError(f"Workflow ComfyUI (JSON au format API) introuvable : {workflow}")
            chosen[role] = {"engine": engine, "workflow": workflow}
        data["image_engines"] = chosen
        steps = {}
        for row in engines:
            value = str(row.get("steps") or "").strip()
            if value:
                if not value.isdigit() or not 1 <= int(value) <= 100:
                    raise ValueError("Le nombre d'étapes doit être entre 1 et 100")
                steps[row["role"]] = int(value)
        data["comfy_steps"] = steps  # vide : on garde le nombre d'étapes du workflow
    if "comfy_free_memory" in body:
        data["comfy_free_memory"] = bool(body["comfy_free_memory"])
    if "unload_ollama_before_comfy" in body:
        data["unload_ollama_before_comfy"] = bool(body["unload_ollama_before_comfy"])
    if "free_comfy_before_ollama" in body:
        data["free_comfy_before_ollama"] = bool(body["free_comfy_before_ollama"])
    appsettings.save(data)

def save_settings(body: dict) -> dict:
    provider = body.get("text_provider", "")
    if provider not in TEXT_LABELS or (paths.KIDS and provider not in KIDS_TEXT):
        raise ValueError("Fournisseur d'écriture inconnu")
    model = str(body.get("text_model", "")).strip()
    if model:
        overrides = {}
        if paths.llm_models_file().exists():
            overrides = yaml.safe_load(paths.llm_models_file().read_text(encoding="utf-8")) or {}
        overrides.setdefault(provider, {})["model"] = model
        paths.atomic_write(paths.llm_models_file(), yaml.safe_dump(overrides, allow_unicode=True))
    with S.LOCK:
        st = S.load()
        appsettings.set_provider("text", provider)
        S.save(st)
    save_settings_tasks(body)
    return {"ok": True, **settings_view()}

def set_max_plans(n: int) -> dict:
    if n not in PLAN_LIMITS:
        raise ValueError("Choisissez un nombre de plans proposés entre 1 et 8, ou « autant que je veux »")
    with S.LOCK:
        st = S.load()
        st["settings"]["max_plans"] = n
        S.save(st)
    return {"ok": True, "max_plans": n}
